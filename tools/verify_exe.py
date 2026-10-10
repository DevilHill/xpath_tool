"""对打包后的 dist/XPathStudio.exe 做真实进程级验证。

会以 --serve 模式启动 exe，调用健康检查、静态资源与扩展桥接用的配置接口，
然后关闭进程。用法：python tools/verify_exe.py
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import crx  # noqa: E402

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_handshake(host: str, port: int, path: str = "/ws"):
    """对打包后的 exe 做一次真实 WebSocket 握手，返回 (响应头文本, 期望的 Accept)。"""
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    s = socket.create_connection((host, port), timeout=6)
    try:
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.sendall(req.encode("ascii"))
        buf = b""
        s.settimeout(6)
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    head = buf.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    expect = base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    ).decode("ascii")
    return head, expect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "XPathStudio.exe")
CONFIG = os.path.join(os.path.expanduser("~"), ".xpath_studio", "config.json")
with socket.socket() as _port_probe:
    _port_probe.bind(("127.0.0.1", 0))
    PORT = _port_probe.getsockname()[1]
BASE = f"http://127.0.0.1:{PORT}"


def close_test_process(proc):
    """onefile 的服务运行在子进程；只结束父进程会留下旧服务。"""
    if os.name == "nt":
        # 只清理本次启动的直接子进程，核对路径、父 PID 和创建时间，防 PID 复用。
        script = r'''
$nodes = @(Get-CimInstance Win32_Process -Filter "Name = 'XPathStudio.exe'" |
    Where-Object { $_.ExecutablePath -eq $env:XPS_VERIFY_EXE -and $_.ParentProcessId -eq [int]$env:XPS_VERIFY_PARENT })
foreach ($node in $nodes) {
    $live = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $node.ProcessId)
    if ($live -and $live.CreationDate -eq $node.CreationDate -and
        $live.ExecutablePath -eq $env:XPS_VERIFY_EXE -and $live.ParentProcessId -eq [int]$env:XPS_VERIFY_PARENT) {
        Stop-Process -Id $live.ProcessId -ErrorAction SilentlyContinue
    }
}
'''
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                       env=dict(os.environ, XPS_VERIFY_EXE=EXE, XPS_VERIFY_PARENT=str(proc.pid)),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=True)
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def call(path: str, payload: dict | None = None, method: str | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main() -> int:
    if not os.path.exists(EXE):
        print(f"找不到 {EXE}，请先执行 python build.py")
        return 1

    # 备份用户真实配置，测试结束后还原
    backup = None
    if os.path.exists(CONFIG):
        backup = open(CONFIG, "rb").read()

    print(f"启动 {EXE} --serve --port {PORT} ...")
    proc = subprocess.Popen([EXE, "--serve", "--port", str(PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True
    try:
        # 轮询等待服务就绪
        ready = False
        for _ in range(60):
            if proc.poll() is not None:
                print("exe 提前退出 ❌")
                return 1
            try:
                st, body = call("/api/health")
                if st == 200:
                    ready = True
                    print(f"[1] /api/health     -> {body}")
                    break
            except Exception:
                time.sleep(0.5)
        if not ready:
            print("服务未在 30s 内就绪 ❌")
            return 1

        # 静态资源
        with urllib.request.urlopen(BASE + "/", timeout=10) as r:
            html = r.read().decode("utf-8")
        print(f"[2] GET /            -> {r.status}, 含标题: {'XPath Studio' in html}")
        served: dict[str, bytes] = {"index.html": html.encode("utf-8")}
        for asset in ("app.js", "style.css", "app.ico"):
            try:
                with urllib.request.urlopen(f"{BASE}/{asset}", timeout=10) as r:
                    served[asset] = r.read()
                    print(f"    /{asset:12s} -> {r.status}, {len(served[asset])} 字节")
            except Exception as exc:  # noqa: BLE001
                ok = False
                print(f"    /{asset:12s} -> 失败 {exc}")

        # 扩展桥接配置接口
        st, cfg = call("/api/config", method="GET")
        print(f"[3] GET /api/config  -> {st}, {cfg}")

        st, saved = call("/api/config", {"config": {
            "baseUrl": "https://api.deepseek.com", "apiKey": "sk-test-123456",
            "model": "deepseek-chat", "enabled": True,
        }})
        print(f"[4] POST /api/config -> {st}, {saved}")

        st, cfg2 = call("/api/config", method="GET")
        inner = cfg2.get("config", {})
        assert inner.get("apiKey") == "***", f"读取时未掩码: {inner}"
        assert inner.get("model") == "deepseek-chat"
        assert inner.get("configured") is True
        print(f"[5] GET /api/config  -> configured={inner.get('configured')}, "
              f"model={inner.get('model')}, apiKey={inner.get('apiKey')}")

        # 用 *** 提交应保留原密钥
        st, saved2 = call("/api/config", {"config": {"apiKey": "***", "model": "deepseek-chat"}})
        st, cfg3 = call("/api/config", method="GET")
        inner3 = cfg3.get("config", {})
        assert inner3.get("apiKey") == "***", "保留密钥失败"
        assert inner3.get("configured") is True
        print(f"[6] POST 保留密钥    -> {st}, 仍为已配置状态 configured={inner3.get('configured')}")

        # WebSocket 桥接
        head, expect = ws_handshake("127.0.0.1", PORT)
        first_line = head.splitlines()[0] if head else "(无响应)"
        assert "101" in first_line, f"WebSocket 握手未返回 101: {first_line}"
        assert expect in head, "Sec-WebSocket-Accept 计算不一致"
        print(f"[7] WS /ws 握手      -> {first_line}（Accept 校验通过）")

        st, res = call("/api/health", method="GET")
        assert "bridge" in res, f"health 缺少 bridge 字段: {res}"
        print(f"[8] /api/health      -> bridge={res['bridge']}")

        st, res = call("/api/bridge/pick", {})
        assert res.get("ok") is False and "扩展" in (res.get("error") or ""), f"无扩展时 pick 行为异常: {res}"
        print(f"[9] /api/bridge/pick -> 无扩展时返回可读错误 ✅")

        st, res = call("/api/bridge/result", {"payload": {"tag": "button", "xpath": "//button"}})
        assert res.get("ok") is True
        st, res = call("/api/bridge/last", method="GET")
        assert (res.get("payload") or {}).get("tag") == "button", f"兜底回传未生效: {res}"
        print("[10] 兜底回传链路     -> /api/bridge/result -> /api/bridge/last ✅")

        # ---- 扩展一键安装：打包后必须能从 _MEIPASS 释放出可加载的扩展目录 ----
        st, res = call("/api/extension/browsers", method="GET")
        assert res.get("ok") is True, f"浏览器探测失败: {res}"
        ext_dir = Path(res.get("extDir") or "")
        assert ext_dir and ext_dir.is_dir(), f"扩展目录不存在: {ext_dir}（dirError={res.get('dirError')!r}）"
        assert (ext_dir / "manifest.json").is_file(), f"扩展目录缺少 manifest.json: {ext_dir}"
        assert (ext_dir / "background.js").is_file(), f"扩展目录缺少 background.js: {ext_dir}"
        assert (ext_dir / "lib" / "engine.js").is_file(), f"扩展目录缺少 lib/engine.js: {ext_dir}"
        for asset in ("manifest.json", "lib/engine.js", "content.js", "ui.js"):
            assert (ext_dir / asset).read_bytes() == (Path(ROOT) / "extension" / asset).read_bytes(), \
                f"exe 内扩展资源与源码不一致：{asset}"
        # 打包运行时必须释放到稳定路径（_MEIPASS 每次启动都变，不能直接给浏览器）
        assert "XPathStudio" in str(ext_dir), f"未释放到稳定目录: {ext_dir}"
        print(f"[11] /api/extension/browsers -> 探测到 {len(res.get('browsers') or [])} 个浏览器，"
              f"扩展已释放到 {ext_dir} ✅")
        for b in (res.get("browsers") or []):
            print(f"       {b['name']:<18} {b['version']:<16} 推荐={b['recommend']}")

        # 释放出来的副本端口必须被改写成 exe 的真实端口
        bg = (ext_dir / "background.js").read_text(encoding="utf-8")
        assert f"http://127.0.0.1:{PORT}" in bg, f"扩展默认桥接端口未改写为 {PORT}"
        print(f"[12] 扩展副本端口改写 -> DEFAULT_BRIDGE = http://127.0.0.1:{PORT} ✅")

        # ---- 静态资源必须与源码一致 ----
        # 这条专门防「改了前端但忘了重新打包」：exe 里的是 _MEIPASS/web 下的旧副本，
        # 源码看着已经修好了，用户装的 exe 却还是坏的。（「安装扩展」弹窗布局崩掉
        # 就是这么被发现迟了的。）样式是否真的正确由 tools/test_modal_css.js 保证，
        # 这里只保证「打包进去的就是当前源码」。
        web_dir = Path(ROOT) / "app" / "web"
        drift = []
        for asset, data in served.items():
            src = web_dir / asset
            if not src.is_file():
                continue
            want = src.read_bytes()
            if want != data:
                drift.append(f"{asset}（源码 {len(want)} 字节 / exe 内 {len(data)} 字节）")
        assert not drift, (
            "打包产物与源码不一致，请重新执行 python build.py：\n    "
            + "\n    ".join(drift)
        )
        print(f"[13] 静态资源与源码一致 -> {', '.join(served)} ✅（改动前端后必须重新打包）")

        # ---- 企业策略的更新服务：策略里的 update_url 就指向这两个端点 ----
        with urllib.request.urlopen(BASE + "/extension/update.xml", timeout=40) as r:
            xml = r.read().decode("utf-8")
            xml_ct = r.headers.get("Content-Type") or ""
        assert "<gupdate" in xml, f"update.xml 内容异常: {xml[:200]}"
        assert "protocol='2.0'" in xml, f"update.xml 缺 protocol: {xml[:200]}"
        m = re.search(r"appid='([a-p]{32})'", xml)
        assert m, f"update.xml 里没有合法的 appid: {xml[:200]}"
        app_id = m.group(1)
        assert f"codebase='http://127.0.0.1:{PORT}/extension/extension.crx'" in xml, \
            f"update.xml 的 codebase 没指向本机端口: {xml[:300]}"
        print(f"[14] /extension/update.xml -> appid={app_id} 指向本机 {PORT} 端口 ✅")

        with urllib.request.urlopen(BASE + "/extension/extension.crx", timeout=60) as r:
            crx_bytes = r.read()
            crx_ct = r.headers.get("Content-Type") or ""
        assert crx_bytes[:4] == b"Cr24", f"CRX 魔数不对: {crx_bytes[:4]!r}"
        assert crx_bytes[4:8] == bytes([3, 0, 0, 0]), f"CRX 版本不是 3: {crx_bytes[4:8]!r}"
        # 解析回来并验签，确认 exe 里真的能生成「Chrome 认得的」CRX3
        parsed = crx.parse_crx3(crx_bytes)
        assert parsed["zip"][:2] == b"PK", "CRX 尾部不是 zip"
        with zipfile.ZipFile(io.BytesIO(parsed["zip"])) as z:
            names = z.namelist()
            assert "manifest.json" in names, f"CRX 内 zip 缺 manifest.json: {names}"
            inner = json.loads(z.read("manifest.json").decode("utf-8"))
        assert inner.get("key"), "CRX 内 manifest 没注入 key（会导致扩展 ID 与签名不一致）"
        # CRX 头里的公钥必须与 manifest 的 key 一致
        assert base64.b64decode(inner["key"]) == parsed["public_key"], \
            "CRX 签名公钥与 manifest key 不一致"
        # crx_id 必须与 appid 对应
        signed_fields = dict(crx.pb_fields(parsed["signed_header_data"]))
        assert crx.encode_app_id(signed_fields[1]) == app_id, \
            "CRX 内的 crx_id 与 update.xml 的 appid 不一致"
        print(f"[15] /extension/extension.crx -> {len(crx_bytes)} 字节，"
              f"CRX3 合法、含 {len(names)} 个文件、appid 与 update.xml 一致 ✅")

        # 不调用 /api/extension/install：它会真的启动浏览器（会弹窗）。
        # 安装逻辑本身由 tools/test_extension_installer.py（56 项，桩掉 Popen）
        # 与 tools/live_install_check.py（真机）覆盖。

        print("\n打包 exe 验证通过 ✅")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"\n验证失败 ❌ {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        close_test_process(proc)
        print("已关闭 exe 进程")
        # 还原用户原配置
        try:
            if backup is None:
                if os.path.exists(CONFIG):
                    os.remove(CONFIG)
            else:
                open(CONFIG, "wb").write(backup)
            print("已还原原配置")
        except Exception as exc:  # noqa: BLE001
            print(f"还原配置失败（可忽略）：{exc}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
