"""在真实浏览器里渲染「安装扩展」弹窗，截图 + 量真实像素几何。

为什么需要它：jsdom 能解析 CSS 级联（`tools/test_modal_css.js`），但**不做布局**，
量不到真实盒模型。而「安装扩展」弹窗崩掉是个纯视觉问题（单选按钮撑满整行、浏览器名被
挤成竖排单字），必须用真实渲染引擎量。

做法：起 exe（`--serve`）→ 起无头 Chrome 打开 exe 的真实页面 → 用 CDP 点开弹窗
→ `Runtime.evaluate` 量 `getBoundingClientRect()` → `Page.captureScreenshot` 存图。

用法：
    python tools/shot_install_modal.py                # 截图 + 几何断言
    python tools/shot_install_modal.py --port 8794    # 指定端口
    python tools/shot_install_modal.py --outdir shots # 指定输出目录
"""
from __future__ import annotations

import argparse
import base64
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
EXE = os.path.join(ROOT, "dist", "XPathStudio.exe")

# 量真实盒模型：单选按钮必须窄（不能吃满整行），浏览器名必须有正常可用宽度。
# 阈值取得很宽松 —— 只要布局是「正常」的量级即可，不追求像素级精确。
PROBE = r"""
(() => {
  const out = { errors: [] };
  const modal = document.querySelector('#installModal .modal');
  if (!modal) { out.errors.push('找不到弹窗'); return out; }
  out.modalVisible = !document.querySelector('#installModal').hidden;

  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), y: Math.round(r.y) };
  };

  out.modal = rect(modal);
  out.viewport = { w: window.innerWidth, h: window.innerHeight };

  const items = [...document.querySelectorAll('#installBrowsers .browser-item')];
  out.browserCount = items.length;
  out.rows = items.map((it) => {
    const radio = it.querySelector('input[type="radio"]');
    const main = it.querySelector('.browser-main');
    const name = it.querySelector('.browser-name');
    const cs = radio ? getComputedStyle(radio) : null;
    return {
      row: rect(it),
      radio: rect(radio),
      radioCss: cs ? { width: cs.width, flexGrow: cs.flexGrow, padding: cs.padding } : null,
      main: rect(main),
      name: rect(name),
      nameText: name ? name.textContent.trim().slice(0, 40) : '',
      nameLines: name ? Math.round(name.getBoundingClientRect().height /
                   Math.max(1, parseFloat(getComputedStyle(name).lineHeight) || 1)) : 0,
    };
  });

  const adv = document.querySelector('#installAdvBody');
  out.advVisible = adv ? !adv.hidden : false;
  const advRadio = document.querySelector('.radio-row input[type="radio"]');
  out.advRadio = rect(advRadio);
  out.advRadioRow = rect(document.querySelector('.radio-row'));

  const checkbox = document.querySelector('#installAdv');
  out.checkbox = rect(checkbox);
  out.checkboxCss = checkbox
    ? { width: getComputedStyle(checkbox).width, flexGrow: getComputedStyle(checkbox).flexGrow }
    : null;

  out.modalOverflowsViewport = out.modal ? (out.modal.y < 0 ||
      out.modal.y + out.modal.h > window.innerHeight + 1) : null;
  return out;
})()
"""


def _wait_http(url: str, tries: int = 80, delay: float = 0.5):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            time.sleep(delay)
    return None


def _find_chrome() -> str | None:
    for b in ei.find_browsers():
        if b["key"] in ("chrome", "chromium", "edge"):
            return b["path"]
    return None


def _page_ws(port: int, want_host: str) -> str | None:
    """从 CDP 的 /json/list 里挑出目标页面的 webSocketDebuggerUrl。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
            tabs = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for t in tabs:
        if t.get("type") == "page" and want_host in (t.get("url") or ""):
            return t.get("webSocketDebuggerUrl")
    return None


def _eval(conn: WSClientConn, expr: str, mid: int, timeout: float = 20.0):
    resp = conn.call("Runtime.evaluate",
                     {"expression": expr, "returnByValue": True, "awaitPromise": True},
                     msg_id=mid, timeout=timeout)
    if not resp:
        return None
    res = (resp.get("result") or {}).get("result") or {}
    if res.get("subtype") == "error":
        return None
    return res.get("value")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8794)
    ap.add_argument("--debug-port", type=int, default=9223)
    ap.add_argument("--outdir", default=os.path.join(ROOT, "shots"))
    args = ap.parse_args()

    if not os.path.exists(EXE):
        print(f"找不到 {EXE}，请先执行 python build.py")
        return 1
    chrome = _find_chrome()
    if not chrome:
        print("没找到可用的 Chrome / Edge / Chromium")
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="xps-shot-")
    exe_proc = chrome_proc = None
    conn = None
    ok = True

    try:
        print(f"[1] 启动 exe：{EXE} --serve --port {args.port}")
        exe_proc = subprocess.Popen([EXE, "--serve", "--port", str(args.port)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{args.port}"
        if _wait_http(base + "/api/health") is None:
            print("    服务未就绪 ❌")
            return 1
        print("    服务就绪 ✅")

        url = base + "/"
        print(f"[2] 启动无头浏览器：{os.path.basename(chrome)} --headless=new")
        chrome_proc = subprocess.Popen([
            chrome, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            f"--remote-debugging-port={args.debug_port}",
            f"--user-data-dir={profile}",
            "--window-size=1280,1000",
            url,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        ws_url = None
        for _ in range(60):
            ws_url = _page_ws(args.debug_port, f"127.0.0.1:{args.port}")
            if ws_url:
                break
            time.sleep(0.5)
        if not ws_url:
            print("    拿不到页面调试地址 ❌")
            return 1
        print("    页面已打开 ✅")

        conn = WSClientConn(ws_url, timeout=20.0)
        conn.connect()
        mid = [0]

        def call_eval(expr):
            mid[0] += 1
            return _eval(conn, expr, mid[0])

        # 等页面与 app.js 都就绪：app.js 末尾才绑 #bridgeChip 的 click，
        # 早点点等于什么都没发生（弹窗不出现，静默失败）。
        for _ in range(80):
            if call_eval("document.readyState") == "complete" and \
                    call_eval("!!document.querySelector('#bridgeChip')"):
                break
            time.sleep(0.25)
        time.sleep(0.4)

        # 点开弹窗：等价于用户点顶栏的连接状态胶囊。带重试，直到弹窗真的可见。
        opened = False
        for _ in range(20):
            call_eval("document.querySelector('#bridgeChip').click(); 'clicked'")
            time.sleep(0.3)
            if call_eval("!document.querySelector('#installModal').hidden"):
                opened = True
                break
        if not opened:
            print("    弹窗没能打开 ❌（app.js 的 click 未绑定或初始化报错）")
            ok = False

        # 等浏览器列表被 /api/extension/browsers 填充
        for _ in range(40):
            n = call_eval("document.querySelectorAll('#installBrowsers .browser-item').length")
            if n:
                break
            time.sleep(0.25)
        time.sleep(0.6)

        geo = call_eval(PROBE) or {}
        if geo.get("errors"):
            print(f"    探测报错：{geo['errors']}")
            ok = False

        # ---- 几何断言：真实盒模型 ----
        print(f"[3] 真实布局测量（视口 {geo.get('viewport')}，弹窗 {geo.get('modal')}）")
        checks: list[tuple[str, bool, str]] = []

        def add(name, cond, detail=""):
            checks.append((name, bool(cond), detail))

        add("弹窗可见", geo.get("modalVisible"))
        add("探测到浏览器行", (geo.get("browserCount") or 0) > 0,
            f"{geo.get('browserCount')} 行")
        add("弹窗未溢出视口", geo.get("modalOverflowsViewport") is False,
            str(geo.get("modalOverflowsViewport")))

        for i, r in enumerate(geo.get("rows") or []):
            label = r.get("nameText") or f"第{i + 1}行"
            rw = (r.get("row") or {}).get("w") or 0
            rad = r.get("radio") or {}
            main = r.get("main") or {}
            nm = r.get("name") or {}
            # 单选按钮宽度必须远小于整行 —— 之前它等于整行宽度，这就是 bug
            add(f"{label}：单选按钮很窄（{rad.get('w')}px / 行宽 {rw}px）",
                rad.get("w", 999) <= 30 and (rw == 0 or rad.get("w", 999) < rw * 0.2),
                f"radio={rad.get('w')} row={rw}")
            # 注意：真实浏览器会把 `width: auto` 解析成**实际用值**（13px），
            # 而 jsdom 只回声明值 "auto"。所以这里只断言 flexGrow / padding
            # 这类真正参与计算的值；「声明就是 auto」由 tools/test_modal_css.js 断言。
            css = r.get("radioCss") or {}
            add(f"{label}：单选按钮不抢宽度（flex-grow={css.get('flexGrow')}）",
                css.get("flexGrow") == "0", str(css))
            add(f"{label}：单选按钮不撑高（padding={css.get('padding')}）",
                css.get("padding") == "0px", str(css))
            # 文字区必须有正常宽度（之前被压到极窄 → 竖排单字）
            add(f"{label}：文字区宽度正常（{main.get('w')}px）",
                main.get("w", 0) > 300, f"main={main.get('w')}")
            add(f"{label}：浏览器名没有被挤成竖排（高度 {nm.get('h')}px）",
                nm.get("h", 999) <= 60, f"name h={nm.get('h')}")

        if geo.get("advRadio") is not None:
            add("高级选项里的单选按钮也很窄", (geo.get("advRadio") or {}).get("w", 999) <= 30,
                str(geo.get("advRadio")))
        add("复选按钮很窄", (geo.get("checkbox") or {}).get("w", 999) <= 30,
            str(geo.get("checkbox")))

        for name, good, detail in checks:
            print(f"    [{'OK' if good else 'FAIL'}] {name}"
                  + (f"  ({detail})" if detail and not good else ""))
            if not good:
                ok = False

        # ---- 截图 ----
        shots = []
        for tag, prep in (
            ("collapsed", None),
            ("advanced", "const a=document.querySelector('#installAdv');"
                         " if(a && !a.checked){a.click();} 'ok'"),
        ):
            if prep:
                call_eval(prep)
                time.sleep(0.5)
            mid[0] += 1
            resp = conn.call("Page.captureScreenshot",
                             {"format": "png", "captureBeyondViewport": True},
                             msg_id=mid[0], timeout=20.0)
            data = ((resp or {}).get("result") or {}).get("data")
            if not data:
                print(f"    截图失败：{tag}")
                ok = False
                continue
            path = os.path.join(args.outdir, f"install-modal-{tag}.png")
            with open(path, "wb") as f:
                f.write(base64.b64decode(data))
            shots.append(path)
            print(f"[4] 已保存截图 {path}")

        print()
        if ok:
            print("真实浏览器渲染验证通过 ✅")
        else:
            print("真实浏览器渲染验证失败 ❌")
        for s in shots:
            print(f"  截图：{s}")
        return 0 if ok else 1

    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"\n失败 ❌ {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        for p in (chrome_proc, exe_proc):
            if p is None:
                continue
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(profile, ignore_errors=True)
        print("已清理进程与临时 profile")


if __name__ == "__main__":
    sys.exit(main())
