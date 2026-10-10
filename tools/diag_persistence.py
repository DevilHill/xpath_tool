"""严格判定：安装后**重启浏览器**，扩展到底还在不在？

之前的判定用「扩展的 service worker target 是否出现」，这是**不可靠**的 ——
MV3 的 service worker 是事件驱动的，扩展装了但 SW 没被唤醒时，target 列表里
根本不会出现它，会得到假阴性。

这里改用真正可靠的两个证据：
  1. 打开一个普通网页，检查内容脚本是否自动注入 → `window.__XPS_CONTENT_LOADED__`
     （manifest 的 content_scripts 会自动注入，装了才会是 true）
  2. profile 的 Preferences / Secure Preferences 里有没有该扩展的条目

用法：python tools/diag_persistence.py
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

PAGE = b"<!DOCTYPE html><html><head><meta charset='utf-8'><title>t</title></head><body><p>hi</p></body></html>"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *a):  # noqa: A003
        pass


class Browser:
    def __init__(self, chrome: str, profile: str, extra: list[str]):
        self.port = ei._free_port()
        self.proc = subprocess.Popen(
            [chrome, "--headless=new", "--disable-gpu", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={profile}", "--no-proxy-server",
             "--enable-unsafe-extension-debugging",
             "--no-first-run", "--no-default-browser-check", *extra, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.conn: WSClientConn | None = None
        ws = ei._wait_debugger(self.port)
        if ws:
            self.conn = WSClientConn(ws, timeout=20.0)
            self.conn.connect()
            self.conn.call("Target.setDiscoverTargets", {"discover": True}, msg_id=1, timeout=6.0)
        self._mid = 100

    def next_id(self) -> int:
        self._mid += 1
        return self._mid

    def open_page(self, url: str) -> str:
        r = self.conn.call("Target.createTarget", {"url": url},
                           msg_id=self.next_id(), timeout=10.0)
        return ((r or {}).get("result") or {}).get("targetId") or ""

    def page_eval(self, target_id: str, expr: str):
        att = self.conn.call("Target.attachToTarget", {"targetId": target_id, "flatten": True},
                             msg_id=self.next_id(), timeout=8.0)
        sid = ((att or {}).get("result") or {}).get("sessionId") or ""
        if not sid:
            return None
        r = self.conn.call("Runtime.evaluate",
                           {"expression": expr, "awaitPromise": True, "returnByValue": True},
                           msg_id=self.next_id(), timeout=10.0, session_id=sid)
        return (((r or {}).get("result") or {}).get("result") or {}).get("value")

    def content_script_present(self, url: str) -> tuple[bool, str]:
        """打开页面，看内容脚本有没有自动注入。

        注意：内容脚本跑在**隔离世界**里，`window.__XPS_CONTENT_LOADED__` 对
        CDP 主世界的 `Runtime.evaluate` 是**不可见**的，所以这个办法不可靠，
        仅作参考。真正判定用 `installed_extensions()`。
        """
        tid = self.open_page(url)
        time.sleep(3.0)
        val = self.page_eval(tid, "String(window.__XPS_CONTENT_LOADED__)")
        return val == "true", str(val)

    # 遍历 chrome://extensions 的 shadow DOM，列出已安装扩展的名字
    LIST_EXPR = """
    (() => {
      const mgr = document.querySelector('extensions-manager');
      if (!mgr || !mgr.shadowRoot) return 'NO_MANAGER';
      const list = mgr.shadowRoot.querySelector('extensions-item-list');
      if (!list || !list.shadowRoot) return 'NO_LIST';
      const items = list.shadowRoot.querySelectorAll('extensions-item');
      const out = [];
      for (const it of items) {
        if (!it.shadowRoot) continue;
        const n = it.shadowRoot.querySelector('#name');
        out.push(n ? n.textContent.trim() : '(无名)');
      }
      return JSON.stringify(out);
    })()
    """

    def installed_extensions(self) -> list[str] | None:
        """真正可靠的判定：chrome://extensions 上列出的扩展名字。"""
        tid = self.open_page("chrome://extensions/")
        if not tid:
            return None
        time.sleep(3.5)
        val = self.page_eval(tid, self.LIST_EXPR)
        if not isinstance(val, str) or val.startswith("NO_"):
            return None
        try:
            return json.loads(val)
        except Exception:  # noqa: BLE001
            return None

    def close(self) -> None:
        try:
            if self.conn:
                self.conn.call("Browser.close", {}, msg_id=999, timeout=5.0)
                self.conn.close()
        except Exception:  # noqa: BLE001
            pass
        deadline = time.time() + 20
        while time.time() < deadline and self.proc.poll() is None:
            time.sleep(0.4)
        if self.proc.poll() is None:
            self.proc.kill()


def prefs_probe(profile: str, ext_id: str) -> None:
    """检查 profile 里是否有该扩展的持久化条目。"""
    for name in ("Preferences", "Secure Preferences"):
        p = os.path.join(profile, "Default", name)
        if not os.path.exists(p):
            print(f"    {name}: 文件不存在")
            continue
        size = os.path.getsize(p)
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception as exc:  # noqa: BLE001
            print(f"    {name}: 读取失败 {exc}")
            continue
        has_id = ext_id in txt
        entries = 0
        try:
            entries = len(((json.loads(txt).get("extensions") or {}).get("settings") or {}))
        except Exception:  # noqa: BLE001
            pass
        print(f"    {name}: {size} 字节, extensions.settings 条目={entries}, "
              f"含本扩展 id={has_id}")


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    test_url = f"http://127.0.0.1:{port}/"
    print(f"测试页：{test_url}")

    chrome = [b for b in ei.find_browsers() if b["key"] == "chrome"][0]["path"]
    print(f"浏览器：{chrome}")

    # 基线：全新 profile、不装扩展时，chrome://extensions 里不该有 XPath Studio
    print("\n" + "=" * 72)
    print("[0] 基线：全新 profile，不装扩展")
    print("=" * 72)
    profile = tempfile.mkdtemp(prefix="xps-persist-")
    b = Browser(chrome, profile, [])
    base_list = b.installed_extensions()
    print(f"    chrome://extensions 列表 = {base_list}")
    baseline_ok = bool(base_list is not None) and not any("XPath" in n for n in base_list)
    print(f"    基线{'正常 ✅（没装时确实没有）' if baseline_ok else '异常/无法枚举 ❌'}")

    print("\n" + "=" * 72)
    print("[1] 会话 A：CDP Extensions.loadUnpacked 安装")
    print("=" * 72)
    r = b.conn.call("Extensions.loadUnpacked", {"path": EXT}, msg_id=b.next_id(), timeout=12.0)
    ext_id = ((r or {}).get("result") or {}).get("id") or ""
    print(f"    安装结果 id={ext_id or '(失败)'}  err={(r or {}).get('error')}")
    time.sleep(2.0)
    list_a = b.installed_extensions()
    print(f"    会话 A chrome://extensions 列表 = {list_a}")
    present_a = bool(list_a) and any("XPath" in n for n in list_a)
    b.close()
    time.sleep(1.5)

    print("\n    profile 持久化检查：")
    prefs_probe(profile, ext_id)

    print("\n" + "=" * 72)
    print("[2] 会话 B：同一 profile 重启，**不带任何安装参数**")
    print("=" * 72)
    b2 = Browser(chrome, profile, [])
    list_b = b2.installed_extensions()
    print(f"    会话 B chrome://extensions 列表 = {list_b}")
    present_b = bool(list_b) and any("XPath" in n for n in list_b)
    b2.close()
    shutil.rmtree(profile, ignore_errors=True)
    srv.shutdown()

    print("\n" + "=" * 72)
    print("结论")
    print("=" * 72)
    print(f"  基线（没装时列表里没有）      : {'✅' if baseline_ok else '❌'}")
    print(f"  会话 A（装完立即出现）        : {'✅' if present_a else '❌'}")
    if present_b:
        print("  会话 B（重启后仍在）          : ✅ → Extensions.loadUnpacked 可持久化")
        print("\n  >>> 可以指向真实 profile 实现「一键装进现有浏览器」")
    else:
        print("  会话 B（重启后仍在）          : ❌ → Extensions.loadUnpacked **不持久化**")
        print("\n  >>> 装进真实 profile 只能靠「加载已解压的扩展程序」（guided）或企业策略")
    return 0


if __name__ == "__main__":
    sys.exit(main())
