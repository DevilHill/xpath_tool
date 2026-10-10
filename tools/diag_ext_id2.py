"""诊断：CDP Extensions.loadUnpacked 返回的扩展 ID 是怎么来的？确定性吗？

如果 ID 只由**路径**决定，那就能自己算出 ID、直接把条目写进 profile 的 Preferences，
实现「一键装进现有浏览器」。所以先确认：
  1. 同一路径加载两次，ID 是否一致（确定性）
  2. ID 是否等于 sha256(路径) 前 32 位 hex 映射到 a-p —— 若是，用哪种路径写法
"""
from __future__ import annotations

import hashlib
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
HEX = "0123456789abcdef"
AP = "abcdefghijklmnop"


def formula(path: str) -> str:
    h = hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]
    return "".join(AP[HEX.index(c)] for c in h)


def variants() -> list[str]:
    """路径的各种写法，看哪种能对上实测 ID。"""
    p = EXT
    out = [
        p,
        p.replace("\\", "/"),
        p.lower(),
        p.lower().replace("\\", "/"),
        p + "\\",
        p + "/",
        os.path.abspath(p),
        os.path.normpath(p),
        os.path.realpath(p),
        "\\\\?\\" + p,
    ]
    # 去重保序
    seen, uniq = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def load_unpacked(ws_url: str, path: str) -> tuple[bool, str]:
    conn = WSClientConn(ws_url, timeout=10.0)
    try:
        conn.connect()
        resp = conn.call("Extensions.loadUnpacked", {"path": path}, timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        return False, f"异常 {exc}"
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    if resp and not resp.get("error"):
        return True, ((resp.get("result") or {}).get("id")) or "(无 id)"
    err = (resp or {}).get("error")
    return False, (err.get("message", err) if isinstance(err, dict) else err)


def main() -> int:
    chrome = [b for b in ei.find_browsers() if b["key"] == "chrome"][0]["path"]
    profile = tempfile.mkdtemp(prefix="xps-id-")
    port = ei._free_port()
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "--enable-unsafe-extension-debugging",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = ei._wait_debugger(port)
        if not ws:
            print("调试端口未就绪")
            return 1

        print("=" * 72)
        print("1) 确定性：同一路径连续加载两次")
        print("=" * 72)
        ids = []
        for i in (1, 2):
            ok, val = load_unpacked(ws, EXT)
            print(f"  第 {i} 次：ok={ok} id={val}")
            ids.append(val)
        print(f"  {'✅ 确定性（两次一致）' if ids[0] == ids[1] else '❌ 不确定（每次不同 → ID 不是路径派生的）'}")

        print()
        print("=" * 72)
        print("2) 公式比对：sha256(路径) -> a-p")
        print("=" * 72)
        target = ids[0]
        print(f"  实测 ID：{target}")
        matched = None
        for v in variants():
            got = formula(v)
            flag = "  <== 命中" if got == target else ""
            print(f"    {got}  <-  {v!r}{flag}")
            if got == target:
                matched = v
        print()
        if matched:
            print(f"  ✅ 公式正确，路径写法为：{matched!r}")
        else:
            print("  ❌ 以上写法都不匹配 —— ID 可能不是由路径派生（如随机或带 salt）")
    finally:
        try:
            conn = WSClientConn(ei._wait_debugger(port) or "", timeout=5.0)
            if conn.url:
                conn.connect()
                conn.call("Browser.close", {}, msg_id=99, timeout=5.0)
                conn.close()
        except Exception:  # noqa: BLE001
            pass
        deadline = time.time() + 15
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.4)
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
