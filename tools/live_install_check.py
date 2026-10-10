"""真机验证：桌面版一键安装扩展后，扩展能否通过 WebSocket 连回来。

这是**唯一能证明「安装真的成功」的方式** —— 命令返回成功并不代表扩展被加载了
（品牌版 Chrome 137+ 会静默忽略 --load-extension）。

会用独立 profile 启动一个浏览器窗口，验证完自动关掉，不影响用户日常配置。

用法：
    python tools/live_install_check.py                     # 默认 edge + flag
    python tools/live_install_check.py --browser chrome    # 品牌版 Chrome（走 cdp）
    python tools/live_install_check.py --strategy guided   # 只验证引导流程
    python tools/live_install_check.py --keep              # 不自动关浏览器
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import extension_installer as ei  # noqa: E402
from app import server as srv  # noqa: E402
from app import ws_bridge  # noqa: E402

PORT = 8790


def _kill(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        try:
            if p.poll() is not None:
                continue
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                    capture_output=True, timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                p.terminate()
        except Exception as exc:  # noqa: BLE001
            print(f"  [警告] 关闭进程 {getattr(p, 'pid', '?')} 失败：{exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="edge")
    ap.add_argument("--strategy", default="auto", choices=["auto", "flag", "cdp", "guided"])
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--keep", action="store_true", help="验证完不关浏览器")
    args = ap.parse_args()

    print("=" * 64)
    print(" 真机验证：一键安装扩展 -> 扩展自动连回桌面版")
    print("=" * 64)

    browsers = ei.find_browsers()
    for b in browsers:
        print(f"  检测到 {b['name']:<18} {b['version']:<16} "
              f"flag={'可用' if b['flag'] else '已禁用'} cdp={'可用' if b['cdp'] else '不可用'} 推荐={b['recommend']}")
    if not browsers:
        print("\n[失败] 没有检测到 Chromium 系浏览器")
        return 1

    target = ei.pick_browser(browsers, args.browser)
    print(f"\n  目标浏览器：{target['name']} ({target['version']})")

    print(f"  启动本地服务 127.0.0.1:{PORT} …")
    httpd, port = srv.run_server(PORT)
    if port != PORT:
        print(f"  [警告] 端口被占用，实际使用 {port}（扩展默认连 {PORT}，可能连不上）")
    time.sleep(0.4)
    print(f"  桥接统计（启动前）：{ws_bridge.HUB.stats()}")

    spawned: list[subprocess.Popen] = []
    real_spawn = ei._spawn

    def capture_spawn(exe: str, cargs: list[str]) -> None:
        spawned.append(subprocess.Popen([exe, *cargs], close_fds=True))

    ei._spawn = capture_spawn
    try:
        print(f"\n  执行安装（strategy={args.strategy}）…")
        t0 = time.time()
        res = ei.install(strategy=args.strategy, browser_key=args.browser,
                         port=port, verify_timeout=args.timeout)
        dt = time.time() - t0

        print(f"\n  耗时 {dt:.1f}s")
        for k in ("ok", "strategy", "method", "browser", "version", "connected", "guided", "copied"):
            if k in res:
                print(f"    {k:<10} = {res[k]}")
        for k in ("error", "warning"):
            if res.get(k):
                print(f"    {k:<10} = {res[k]}")
        print(f"    extDir     = {res.get('extDir')}")
        print(f"  桥接统计（安装后）：{ws_bridge.HUB.stats()}")

        if res.get("guided"):
            print("\n  [引导安装] 已打开扩展管理页并复制目录，无法自动判定；"
                  "请按窗口里的步骤手动加载后，再点桌面版的「重新检测连接」。")
            ok = True
        else:
            ok = bool(res.get("connected"))
            print("\n  " + ("[成功] 扩展已通过 WebSocket 连回桌面版 ✅" if ok
                            else "[失败] 浏览器启动了，但扩展没有连回来 ❌"))
            if not ok:
                print("         可尝试：1) 稍等再点「重新检测连接」"
                      "  2) 改用 --strategy guided 手动加载  3) 换 Edge/Chromium")
    finally:
        ei._spawn = real_spawn
        if not args.keep:
            print(f"\n  关闭本次启动的浏览器（{len(spawned)} 个进程）…")
            _kill(spawned)
            time.sleep(1.0)
        httpd.shutdown()

    print("=" * 64)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
