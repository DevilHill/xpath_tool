"""实验：哪种「安装」机制能把扩展**持久化写进浏览器 profile**？

要回答的问题：一键安装现在用 `--user-data-dir` 指向专用目录，装的是**新开的独立实例**，
用户日常那个 profile 里什么都没有。要做到「装进现有浏览器」，必须用能写进真实
profile 的机制。这里在**临时 profile** 上实验，不碰用户真实数据。

判定方法（不依赖桥接服务）：
  - 扩展是否加载：CDP `Target.getTargets` 里有没有 `chrome-extension://<id>/background.js`
    的 `service_worker` 目标
  - 是否持久化：装完后**优雅关闭**，再用**同一 profile、不带任何安装参数**重启，
    如果扩展的 service_worker 目标又出现了 → 说明写进了 profile ✅

注意：
  1. 统一 `--headless=new`。本机直接拉 GUI 版 Chrome 会立刻退出。
  2. 关闭一律走 CDP `Browser.close`（优雅关闭才会 flush Preferences），
     绝不 `taskkill` 一个可能已经退出的 PID —— PID 被复用会误杀无关进程树。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import extension_installer as ei  # noqa: E402
from app.ws_bridge import WSClientConn  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")
HEADLESS = ["--headless=new", "--disable-gpu"]


def chrome_path() -> str:
    for b in ei.find_browsers():
        if b["key"] == "chrome":
            return b["path"]
    raise SystemExit("找不到 Chrome")


def launch(chrome: str, profile: str, port: int, extra: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        [chrome, *HEADLESS, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--enable-unsafe-extension-debugging", "--no-first-run", "--no-default-browser-check",
         *extra, "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def browser_ws(port: int, timeout: float = 25.0) -> str:
    return ei._wait_debugger(port, timeout)


def ext_targets(ws_url: str) -> list[str]:
    """列出当前已加载的扩展 service worker 目标 URL。"""
    conn = WSClientConn(ws_url, timeout=10.0)
    try:
        conn.connect()
        conn.call("Target.setDiscoverTargets", {"discover": True}, msg_id=1, timeout=6.0)
        resp = conn.call("Target.getTargets", {}, msg_id=2, timeout=6.0)
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    infos = ((resp or {}).get("result") or {}).get("targetInfos") or []
    return [t.get("url", "") for t in infos
            if t.get("type") == "service_worker" and "chrome-extension://" in (t.get("url") or "")]


def close_gracefully(ws_url: str, proc: subprocess.Popen, timeout: float = 20.0) -> bool:
    """CDP Browser.close 优雅关闭，等进程真正退出。"""
    try:
        conn = WSClientConn(ws_url, timeout=8.0)
        conn.connect()
        conn.call("Browser.close", {}, msg_id=99, timeout=6.0)
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.4)
    # 兜底：确认还活着才 kill
    if proc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return False


def prefs_ext_entries(profile: str) -> dict:
    p = os.path.join(profile, "Default", "Preferences")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return ((json.load(f).get("extensions") or {}).get("settings") or {})
    except Exception:  # noqa: BLE001
        return {}


def show_prefs(profile: str) -> str:
    entries = prefs_ext_entries(profile)
    hit_id = ""
    print(f"    Preferences 扩展条目数：{len(entries)}")
    for k, v in entries.items():
        v = v or {}
        path = v.get("path") or ""
        name = (v.get("manifest") or {}).get("name") or ""
        if "xpath studio" in name.lower() or "xpath" in path.lower():
            hit_id = k
            print(f"    ✅ 找到本扩展 id={k}")
            print(f"       location={v.get('location')} name={name!r}")
            print(f"       path={path}")
    if not hit_id:
        print("    ❌ Preferences 里没有本扩展")
    return hit_id


def run_case(title: str, chrome: str, install_fn) -> bool:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    profile = tempfile.mkdtemp(prefix="xps-exp-")
    port_a = ei._free_port()

    # ---- 会话 A：安装 ----
    proc = launch(chrome, profile, port_a, [])
    ws_a = browser_ws(port_a)
    if not ws_a:
        print("  ❌ 调试端口未就绪")
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        return False

    ok, detail = install_fn(ws_a, profile)
    print(f"  安装：{'成功' if ok else '失败'} —— {detail}")
    time.sleep(2.5)

    loaded_a = ext_targets(ws_a)
    print(f"  会话 A 已加载的扩展 SW：{loaded_a or '（无）'}")

    close_gracefully(ws_a, proc)
    time.sleep(1.5)
    print("  已优雅关闭，检查 Preferences：")
    hit = show_prefs(profile)

    # ---- 会话 B：同一 profile，不带任何安装参数 ----
    port_b = ei._free_port()
    print("  用同一 profile 重启（不带任何安装参数）…")
    proc_b = launch(chrome, profile, port_b, [])
    ws_b = browser_ws(port_b)
    loaded_b = ext_targets(ws_b) if ws_b else []
    print(f"  会话 B 已加载的扩展 SW：{loaded_b or '（无）'}")
    if ws_b:
        close_gracefully(ws_b, proc_b)
    elif proc_b.poll() is None:
        proc_b.kill()

    persisted = bool(loaded_b) and any("chrome-extension://" in u for u in loaded_b)
    print(f"\n  >>> 结论：{'可持久化 ✅（重启后扩展仍在）' if persisted else '不持久化 ❌（重启后扩展消失）'}")
    if hit and not persisted:
        print("      （Preferences 里有条目，但重启后没加载 → 只写了一半，不能算装好）")
    shutil.rmtree(profile, ignore_errors=True)
    return persisted


def install_via_flag(ws_url: str, profile: str):
    # 用 --load-extension 需要重启进程，这里改成在已启动的实例上做不到，
    # 所以单独走一条路径：直接再起一个带 --load-extension 的实例
    return False, "见 exp_load_extension_flag（需要带参数启动）"


def main() -> int:
    chrome = chrome_path()
    print(f"Chrome: {chrome}")
    print(f"扩展目录: {EXT}")

    results: dict[str, bool] = {}

    # ---------- 实验 1：--load-extension ----------
    print("\n" + "=" * 72)
    print("实验 1：--load-extension 能否持久化进 profile？")
    print("=" * 72)
    profile = tempfile.mkdtemp(prefix="xps-exp1-")
    port = ei._free_port()
    proc = subprocess.Popen(
        [chrome, *HEADLESS, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         f"--load-extension={EXT}", "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = browser_ws(port)
    print(f"  会话 A 已加载的扩展 SW：{ext_targets(ws) if ws else '（无）'}")
    if ws:
        close_gracefully(ws, proc)
    elif proc.poll() is None:
        proc.kill()
    time.sleep(1.5)
    print("  已关闭，检查 Preferences：")
    show_prefs(profile)

    port2 = ei._free_port()
    print("  同一 profile 重启（不带 --load-extension）…")
    proc2 = subprocess.Popen(
        [chrome, *HEADLESS, f"--remote-debugging-port={port2}", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws2 = browser_ws(port2)
    loaded = ext_targets(ws2) if ws2 else []
    print(f"  会话 B 已加载的扩展 SW：{loaded or '（无）'}")
    if ws2:
        close_gracefully(ws2, proc2)
    elif proc2.poll() is None:
        proc2.kill()
    results["--load-extension"] = bool(loaded)
    print(f"\n  >>> 结论：{'可持久化 ✅' if loaded else '不持久化 ❌'}")
    shutil.rmtree(profile, ignore_errors=True)

    # ---------- 实验 2：CDP Extensions.loadUnpacked ----------
    def cdp_install(ws_url: str, _profile: str):
        errors = []
        for method in ("Extensions.loadUnpacked", "browser.addExtension"):
            conn = WSClientConn(ws_url, timeout=10.0)
            try:
                conn.connect()
                resp = conn.call(method, {"path": EXT}, timeout=10.0)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{method}: {exc}")
                continue
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            if resp and not resp.get("error"):
                eid = ((resp.get("result") or {}).get("id")) or ""
                return True, f"{method} ok id={eid}"
            err = (resp or {}).get("error")
            msg = err.get("message", err) if isinstance(err, dict) else err
            errors.append(f"{method}: {msg}")
        return False, "；".join(errors)

    results["CDP loadUnpacked"] = run_case(
        "实验 2：CDP Extensions.loadUnpacked 能否持久化进 profile？", chrome, cdp_install)

    print("\n" + "=" * 72)
    print("汇总")
    print("=" * 72)
    for k, v in results.items():
        print(f"  {k:24s} {'可持久化 ✅' if v else '不持久化 ❌'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
