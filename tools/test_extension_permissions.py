"""扩展权限测试：静态 manifest 校验 + 真实浏览器里的运行时权限探测。

为什么需要它：曾经 `host_permissions` 只写了 `127.0.0.1` / `localhost`，
但 `background.js` 会对**任意页面**调 `chrome.scripting.executeScript`
（内容脚本没注入时的兜底路径）。MV3 里 `content_scripts.matches` **不授予**
编程注入的权限，于是用户在普通网页上抓取时拿到：

    Cannot access contents of the page.
    Extension manifest must request permission to access the respective host.

静态检查抓不到这个（manifest 本身是合法的），必须问浏览器「你到底有没有这个权限」。

用法：python tools/test_extension_permissions.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import extension_installer as ei  # noqa: E402
from app.ws_bridge import WSClientConn  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")
MANIFEST = os.path.join(EXT, "manifest.json")

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -> {detail}" if detail and not ok else ""))


def pattern_covers(host_perms: list[str], url: str) -> bool:
    """粗略判断 url 是否被某条 host_permissions 覆盖（够用即可）。"""
    from urllib.parse import urlparse
    u = urlparse(url)
    origin = f"{u.scheme}://{u.netloc}"
    for p in host_perms:
        if p == "<all_urls>":
            return True
        if p.endswith("/*") and origin.startswith(p[:-2]):
            return True
        if p == f"{origin}/*":
            return True
    return False


# --------------------------------------------------------------------------- #
# 1. 静态检查
# --------------------------------------------------------------------------- #
def static_checks() -> dict:
    print("=" * 72)
    print("1) 静态 manifest 校验")
    print("=" * 72)
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            mf = json.load(f)
    except Exception as exc:  # noqa: BLE001
        check("manifest.json 是合法 JSON", False, str(exc))
        return {}

    check("manifest.json 是合法 JSON", True)
    check("manifest_version 为 3", mf.get("manifest_version") == 3,
          str(mf.get("manifest_version")))

    perms = mf.get("permissions") or []
    host = mf.get("host_permissions") or []
    print(f"    permissions      = {perms}")
    print(f"    host_permissions = {host}")

    check("permissions 含 scripting", "scripting" in perms)
    check("permissions 含 storage", "storage" in perms)
    check("permissions 含 tabs（才能可靠拿到 tab.url）", "tabs" in perms)
    check("permissions 含 alarms", "alarms" in perms)

    # 核心回归点：必须能访问任意站点，否则 executeScript 兜底会报权限错
    check("host_permissions 含 <all_urls>（任意站点可注入）", "<all_urls>" in host,
          str(host))
    check("host_permissions 含 ws://127.0.0.1（桥接长连接）",
          any(h.startswith("ws://127.0.0.1") for h in host), str(host))

    # content_scripts 里声明的页面范围，必须都在 host_permissions 覆盖内
    cs_matches: list[str] = []
    for cs in (mf.get("content_scripts") or []):
        cs_matches.extend(cs.get("matches") or [])
    print(f"    content_scripts.matches = {cs_matches}")
    uncovered = [u for u in cs_matches if not pattern_covers(host, u)]
    check("content_scripts 的每个 matches 都被 host_permissions 覆盖",
          not uncovered, f"未覆盖：{uncovered}")

    # 反例：用一条普通站点 URL 试覆盖，防止 pattern_covers 写得太松
    check("反例校验：https://example.com/ 确实被覆盖",
          pattern_covers(host, "https://example.com/"))
    check("反例校验：https://sub.deep.example.org/ 确实被覆盖",
          pattern_covers(host, "https://sub.deep.example.org/"))

    # 静态再确认：旧写法（只有 127.0.0.1/localhost）应当被判定为「不覆盖普通站点」
    old_host = ["http://127.0.0.1/*", "http://localhost/*",
                "ws://127.0.0.1/*", "ws://localhost/*"]
    check("回归哨兵：旧 host_permissions 不覆盖 https://example.com/",
          not pattern_covers(old_host, "https://example.com/"))
    return mf


# --------------------------------------------------------------------------- #
# 2. 运行时权限探测
# --------------------------------------------------------------------------- #
PROBE_ORIGINS = [
    "https://example.com/*",
    "https://*.github.com/*",
    "http://192.168.1.5/*",
    "https://some-random-site.test/*",
]


def runtime_checks() -> None:
    print()
    print("=" * 72)
    print("2) 真实浏览器里的运行时权限探测")
    print("=" * 72)
    browsers = [b for b in ei.find_browsers() if b["key"] == "chrome"] or ei.find_browsers()
    if not browsers:
        check("找到可用浏览器", False, "没有 Chrome/Edge/Chromium")
        return
    chrome = browsers[0]["path"]
    print(f"    浏览器：{chrome}")

    profile = tempfile.mkdtemp(prefix="xps-perm-")
    port = ei._free_port()
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "--enable-unsafe-extension-debugging",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    conn = None
    try:
        ws_url = ei._wait_debugger(port)
        if not ws_url:
            check("调试端口就绪", False)
            return
        check("调试端口就绪", True)

        conn = WSClientConn(ws_url, timeout=15.0)
        conn.connect()

        resp = conn.call("Extensions.loadUnpacked", {"path": EXT}, msg_id=1, timeout=12.0)
        ext_id = ""
        if resp and not resp.get("error"):
            ext_id = ((resp.get("result") or {}).get("id")) or ""
        check("扩展能被加载（Extensions.loadUnpacked）", bool(ext_id), str(resp))
        if not ext_id:
            return
        print(f"    扩展 id = {ext_id}")

        # 找扩展的 service worker target
        conn.call("Target.setDiscoverTargets", {"discover": True}, msg_id=2, timeout=6.0)
        target_id = ""
        for _ in range(30):
            r = conn.call("Target.getTargets", {}, msg_id=3, timeout=6.0)
            infos = ((r or {}).get("result") or {}).get("targetInfos") or []
            for t in infos:
                if t.get("type") == "service_worker" and ext_id in (t.get("url") or ""):
                    target_id = t.get("targetId") or ""
                    break
            if target_id:
                break
            time.sleep(0.5)
        check("扩展的 service worker 已启动", bool(target_id), "没找到 SW target")
        if not target_id:
            return

        att = conn.call("Target.attachToTarget",
                        {"targetId": target_id, "flatten": True}, msg_id=4, timeout=8.0)
        session_id = ((att or {}).get("result") or {}).get("sessionId") or ""
        check("能附加到扩展的 SW 会话", bool(session_id), str(att))
        if not session_id:
            return

        def sw_eval(expr: str, mid: int):
            r = conn.call("Runtime.evaluate",
                          {"expression": expr, "awaitPromise": True, "returnByValue": True},
                          msg_id=mid, timeout=10.0, session_id=session_id)
            res = ((r or {}).get("result") or {})
            if res.get("exceptionDetails"):
                return None, str(res["exceptionDetails"])[:200]
            return (res.get("result") or {}).get("value"), ""

        # 先确认 chrome.permissions 可用
        val, err = sw_eval("typeof chrome.permissions", 10)
        check("SW 里 chrome.permissions 可用", val == "object", f"{val} {err}")

        # 核心：对普通站点是否真的有 host 权限
        for i, origin in enumerate(PROBE_ORIGINS):
            expr = (f"chrome.permissions.contains({{origins: [{json.dumps(origin)}]}})")
            val, err = sw_eval(expr, 20 + i)
            check(f"对 {origin} 拥有 host 权限", val is True, f"返回 {val} {err}")

        # 也确认声明的权限集里确实列出了 all_urls
        val, err = sw_eval("JSON.stringify(chrome.runtime.getManifest().host_permissions)", 30)
        check("运行时 manifest 的 host_permissions 含 <all_urls>",
              isinstance(val, str) and "<all_urls>" in val, str(val))

        # ---- 错误信息友好化：这些函数是 SW 里的全局，可以直接调 ----
        print("    --- 错误信息友好化 ---")
        cases = [
            # (表达式, 期望为 True 的条件描述, 判定函数)
            ("injectBlockedReason('chrome://extensions/')",
             "chrome:// 被判为不可注入", lambda v: "内置页面" in str(v)),
            ("injectBlockedReason('about:blank')",
             "about: 被判为不可注入", lambda v: "内置页面" in str(v)),
            ("injectBlockedReason('edge://settings')",
             "edge:// 被判为不可注入", lambda v: "内置页面" in str(v)),
            ("injectBlockedReason('https://example.com/')",
             "普通网页不被拦截", lambda v: v == ""),
            ("injectBlockedReason('file:///C:/a.html')",
             "file:// 提示要开文件访问", lambda v: "允许访问文件网址" in str(v)),
            ("injectBlockedReason('https://chromewebstore.google.com/detail/x')",
             "扩展商店被拦截", lambda v: "商店" in str(v)),
            ("isInjectable('chrome://x')", "isInjectable 拒绝 chrome://",
             lambda v: v is False),
            ("isInjectable('https://example.com/')", "isInjectable 放行普通网页",
             lambda v: v is True),
            ("friendlyInjectError('Cannot access contents of the page. Extension manifest must request permission to access the respective host.')",
             "manifest 权限错翻译成中文", lambda v: "host_permissions" in str(v)),
            ("friendlyInjectError('Cannot access contents of url \"about:blank\". Extension manifest must request permission to access this host.')",
             "about: 的 url 错翻译成中文", lambda v: "内置页面" in str(v)),
            ("friendlyInjectError('Could not establish connection. Receiving end does not exist.')",
             "内容脚本缺失提示刷新", lambda v: "刷新页面" in str(v)),
        ]
        for i, (expr, desc, pred) in enumerate(cases):
            val, err = sw_eval(expr, 40 + i)
            check(desc, pred(val), f"得到 {val!r} {err}")

        # 端到端：真的对 about:blank 调 sendToTab，应当返回友好错误而不是抛异常
        tab_id, _ = sw_eval("chrome.tabs.query({}).then(t => t.length ? t[0].id : -1)", 60)
        val, err = sw_eval(
            "sendToTab(" + str(tab_id) + ", {type:'ping'}, 'about:blank')"
            ".then(r => JSON.stringify(r)).catch(e => 'THREW:' + e.message)",
            70)
        check("sendToTab 对不可注入页面返回友好错误（不抛异常）",
              isinstance(val, str) and "THREW" not in val and "内置页面" in val,
              f"tabId={tab_id} 得到 {val!r} {err}")
    except Exception as exc:  # noqa: BLE001
        check("运行时探测未抛异常", False, f"{type(exc).__name__}: {exc}")
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
        shutil.rmtree(profile, ignore_errors=True)


def main() -> int:
    static_checks()
    runtime_checks()
    print()
    print("=" * 72)
    print(f"结果：通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
    print("全部通过 ✅" if not FAIL else "存在失败 ❌")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
