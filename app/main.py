"""XPath Studio —— 应用入口。

用法：
    python -m app.main              # 打开原生窗口（需 pywebview）
    python -m app.main --browser    # 用系统默认浏览器打开
    python -m app.main --port 8123  # 指定端口
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser

from .server import run_server


DEFAULT_PORT = 8790  # 浏览器扩展默认连接的端口


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pick_port(preferred: int) -> int:
    """优先使用固定端口（浏览器扩展据此连接），被占用时顺延，最后退回随机端口。"""
    if preferred:
        for p in range(preferred, preferred + 10):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", p))
                    return p
                except OSError:
                    continue
    return _free_port()


def _wait_ready(port: int, timeout: float = 5.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    return False


def main() -> int:
    # Windows 控制台默认 GBK，中文提示会乱码，尽量切到 UTF-8
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass

    parser = argparse.ArgumentParser(description="XPath Studio")
    parser.add_argument("--browser", action="store_true", help="使用系统浏览器打开")
    parser.add_argument("--serve", action="store_true", help="仅启动本地服务，不打开任何界面")
    parser.add_argument("--port", type=int, default=0, help="指定端口，0 表示使用默认端口 8790")
    args = parser.parse_args()

    port = args.port or DEFAULT_PORT
    port = _pick_port(port)
    httpd, real_port = run_server(port)
    url = f"http://127.0.0.1:{real_port}/"
    _wait_ready(real_port)

    if args.serve:
        print(f"XPath Studio 服务已启动：{url}（Ctrl+C 退出）", flush=True)
        print(f"浏览器扩展桥接地址：http://127.0.0.1:{real_port}", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            httpd.shutdown()
        return 0

    if args.browser:
        webbrowser.open(url)
        print(f"XPath Studio 已启动：{url}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            httpd.shutdown()
        return 0

    # 尝试用 pywebview 打开原生窗口
    try:
        import webview  # type: ignore

        window = webview.create_window(
            "XPath Studio · 定位编辑器",
            url,
            width=1440,
            height=900,
            min_size=(1080, 680),
            text_select=True,
        )
        webview.start()
        httpd.shutdown()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[提示] 原生窗口不可用（{exc}），改用浏览器打开。")
        webbrowser.open(url)
        print(f"XPath Studio 已启动：{url}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            httpd.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
