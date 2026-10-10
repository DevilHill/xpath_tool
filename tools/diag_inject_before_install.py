"""复现并验证用户报的那个错：

    Cannot access contents of the page.
    Extension manifest must request permission to access the respective host.

场景（真实触发路径）：
  1. 页面在扩展**安装之前**就已经打开 → 内容脚本没注入
  2. 桌面版点「抓取元素」→ background `sendToTab` 先 `tabs.sendMessage` → 失败
  3. 兜底走 `chrome.scripting.executeScript` → 这一步需要 **host 权限**
  4. 旧 manifest 的 host_permissions 只有 127.0.0.1/localhost → 报上面那个错

关键点：页面 origin 必须是**非 localhost**，否则旧的 host_permissions 也能过，
测不出问题。这里用 `--host-resolver-rules` 把 `xpstest.local` 映射到 127.0.0.1，
页面 origin 就是 `http://xpstest.local:PORT` —— 旧权限覆盖不到。

用法：python tools/diag_inject_before_install.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import extension_installer as ei  # noqa: E402
from app.ws_bridge import WSClientConn  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")
FAKE_HOST = "xpstest.local"

PAGE = b"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>t</title></head>
<body><button id="login-btn" class="btn">\xe7\x99\xbb\xe5\xbd\x95</button></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *a):  # noqa: A003
        pass


SW_EXPR = """
(async () => {
  const tabs = await chrome.tabs.query({});
  const out = { tabs: [], results: [] };
  for (const t of tabs) {
    out.tabs.push({ id: t.id, url: t.url || null, pendingUrl: t.pendingUrl || null });
    // 跳过扩展自己的页面（chrome-extension:// 本来就不该注入）
    if ((t.url || '').indexOf('chrome-extension://') === 0) continue;
    const r = { id: t.id, url: t.url || null };
    try {
      await chrome.tabs.sendMessage(t.id, {type: 'ping'});
      r.sendMessage = 'ok';
    } catch (e) { r.sendMessage = String((e && e.message) || e); }
    // 兜底路径 —— 这一步就是用户看到的报错来源
    // 必须和 background.js 一样注入**整套**文件，只注入 lib/engine.js 不会注册消息监听
    try {
      await chrome.scripting.executeScript({
        target: {tabId: t.id}, files: ['lib/engine.js', 'ui.js', 'content.js']});
      r.executeScript = 'ok';
    } catch (e) { r.executeScript = String((e && e.message) || e); }
    try {
      await chrome.tabs.sendMessage(t.id, {type: 'ping'});
      r.sendMessageAfter = 'ok';
    } catch (e) { r.sendMessageAfter = String((e && e.message) || e); }
    out.results.push(r);
  }
  return JSON.stringify(out);
})()
"""


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    test_url = f"http://{FAKE_HOST}:{port}/"
    print(f"测试页：{test_url}（{FAKE_HOST} -> 127.0.0.1，origin 非 localhost）")

    chrome = [b for b in ei.find_browsers() if b["key"] == "chrome"][0]["path"]
    profile = tempfile.mkdtemp(prefix="xps-inj-")
    dbg = ei._free_port()
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", f"--remote-debugging-port={dbg}",
         f"--user-data-dir={profile}",
         f"--host-resolver-rules=MAP {FAKE_HOST} 127.0.0.1",
         # 本机装了系统代理时，xpstest.local 会被送去代理并拿到 502，必须绕开
         "--no-proxy-server",
         "--enable-unsafe-extension-debugging",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    conn = None
    try:
        ws_url = ei._wait_debugger(dbg)
        if not ws_url:
            print("调试端口未就绪")
            return 1
        conn = WSClientConn(ws_url, timeout=20.0)
        conn.connect()

        # 1) 先把页面开起来 —— 此时扩展还没加载，内容脚本不会注入
        conn.call("Target.setDiscoverTargets", {"discover": True}, msg_id=1, timeout=6.0)
        r = conn.call("Target.createTarget", {"url": test_url}, msg_id=2, timeout=10.0)
        page_target = ((r or {}).get("result") or {}).get("targetId") or ""
        print(f"已打开页面 target={page_target}（扩展尚未加载）")
        time.sleep(3)

        # 2) 再加载扩展
        r = conn.call("Extensions.loadUnpacked", {"path": EXT}, msg_id=3, timeout=12.0)
        ext_id = ((r or {}).get("result") or {}).get("id") or ""
        print(f"已加载扩展 id={ext_id}")

        # 3) 找 SW 并附加
        target_id = ""
        for _ in range(40):
            rr = conn.call("Target.getTargets", {}, msg_id=4, timeout=6.0)
            for t in (((rr or {}).get("result") or {}).get("targetInfos") or []):
                if t.get("type") == "service_worker" and ext_id in (t.get("url") or ""):
                    target_id = t.get("targetId") or ""
                    break
            if target_id:
                break
            time.sleep(0.5)
        if not target_id:
            print("找不到扩展 SW")
            return 1
        att = conn.call("Target.attachToTarget", {"targetId": target_id, "flatten": True},
                        msg_id=5, timeout=8.0)
        sid = ((att or {}).get("result") or {}).get("sessionId") or ""
        if not sid:
            print("附加 SW 会话失败")
            return 1

        # 4) 在 SW 里跑注入测试
        expr = SW_EXPR.replace("__HOST__", FAKE_HOST)
        rr = conn.call("Runtime.evaluate",
                       {"expression": expr, "awaitPromise": True, "returnByValue": True},
                       msg_id=6, timeout=20.0, session_id=sid)
        res = (rr or {}).get("result") or {}
        if res.get("exceptionDetails"):
            print(f"SW 求值异常：{res['exceptionDetails']}")
            return 1
        raw = (res.get("result") or {}).get("value")
        info = json.loads(raw) if isinstance(raw, str) else (raw or {})
        print()
        print("=" * 72)
        print("注入探测结果")
        print("=" * 72)
        print("  tabs.query 看到的标签页（注意 url 是否为 null）：")
        for t in info.get("tabs", []):
            print(f"    id={t.get('id')} url={t.get('url')!r} pendingUrl={t.get('pendingUrl')!r}")

        print()
        any_ok = False
        for r in info.get("results", []):
            print(f"  标签页 id={r.get('id')} url={r.get('url')!r}")
            print(f"      sendMessage        = {r.get('sendMessage')}")
            print(f"      executeScript      = {r.get('executeScript')}")
            print(f"      sendMessageAfter   = {r.get('sendMessageAfter')}")
            if r.get("executeScript") == "ok":
                any_ok = True
            if "Cannot access contents of the page" in str(r.get("executeScript")):
                print("      ← ❗ 这正是用户报的那个错")

        print()
        if any_ok:
            print(">>> 兜底注入成功 ✅（host 权限足够，安装前打开的页面也能抓）")
        else:
            print(">>> 兜底注入全部失败 ❌（host 权限不足）")
        return 0
    finally:
        try:
            if conn is not None:
                conn.call("Browser.close", {}, msg_id=999, timeout=5.0)
                conn.close()
        except Exception:  # noqa: BLE001
            pass
        deadline = time.time() + 15
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.4)
        if proc.poll() is None:
            proc.kill()
        srv.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
