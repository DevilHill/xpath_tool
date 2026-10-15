"""VS Code 管理的本机浏览器桥，标准输入关闭时退出。"""
from pathlib import Path
import argparse
import json
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        raise ValueError('端口无效')
    try:
        from app.server import create_server
        server = create_server(args.port)
    except ImportError as exc:
        print('缺少 Python 依赖，请执行 WBot: 将 wbot 安装到所选 Python 环境。' + str(exc), file=sys.stderr, flush=True)
        return 1
    except OSError as exc:
        print('无法绑定本机端口：' + str(exc), file=sys.stderr, flush=True)
        return 1

    def watch_parent():
        # 不依赖易复用的进程ID；父扩展退出会关闭此管道。
        sys.stdin.readline()
        server.shutdown()

    threading.Thread(target=watch_parent, daemon=True).start()
    print('__WBOT_BRIDGE__' + json.dumps({'port': server.server_port}), flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
