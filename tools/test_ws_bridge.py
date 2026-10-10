"""WebSocket 桥接测试。

1) 帧编解码单元测试（纯函数，不依赖网络）
2) 端到端：Node 22 内置 WebSocket 客户端 <-> 本服务
   - 客户端 hello 注册为 extension
   - 桌面版 POST /api/bridge/pick -> 客户端收到 start-pick
   - 客户端回传 picked -> 桌面版 HUB.last_pick 收到

用法：python tools/test_ws_bridge.py
"""
from __future__ import annotations

import io
import json
import os
import struct
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ws_bridge  # noqa: E402
from app.server import run_server  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.environ.get("XPS_NODE") or "node"

ok_count = 0
fail_count = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  ✓ {name}")
    else:
        fail_count += 1
        print(f"  ✗ {name} {extra}")


def client_frame(payload: bytes, opcode: int = ws_bridge.OP_TEXT, fin: bool = True) -> bytes:
    """构造一个带掩码的客户端帧，用于测试解码。"""
    b1 = (0x80 if fin else 0) | opcode
    mask = b"\x11\x22\x33\x44"
    n = len(payload)
    if n < 126:
        head = bytes([b1, 0x80 | n])
    elif n < 65536:
        head = bytes([b1, 0x80 | 126]) + struct.pack(">H", n)
    else:
        head = bytes([b1, 0x80 | 127]) + struct.pack(">Q", n)
    masked = bytes(payload[i] ^ mask[i % 4] for i in range(n))
    return head + mask + masked


# --------------------------------------------------------------------------- #
# 1) 帧编解码
# --------------------------------------------------------------------------- #
def test_frames() -> None:
    print("[1] 帧编解码")

    # accept key（RFC 6455 官方示例）
    check("accept_key 与 RFC 示例一致",
          ws_bridge.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    # 服务端编码：短 / 中 / 长三种长度分支
    for n in (5, 200, 70000):
        payload = b"x" * n
        frame = ws_bridge.encode_frame(payload)
        check(f"encode_frame 长度 {n} 首字节 FIN+text", frame[0] == 0x81)
        check(f"encode_frame 长度 {n} 无掩码位", (frame[1] & 0x80) == 0)
        check(f"encode_frame 长度 {n} 长度字段正确", len(frame) - (2 if n < 126 else (4 if n < 65536 else 10)) == n)

    # 解码：短帧
    fin, op, payload = ws_bridge.read_frame(io.BytesIO(client_frame(b"hello")))
    check("read_frame 短帧解出内容", fin is True and op == 1 and payload == b"hello")

    # 解码：中帧（126 分支）
    big = b"a" * 300
    fin, op, payload = ws_bridge.read_frame(io.BytesIO(client_frame(big)))
    check("read_frame 中帧解出内容", payload == big)

    # 解码：长帧（127 分支）
    huge = b"b" * 70000
    fin, op, payload = ws_bridge.read_frame(io.BytesIO(client_frame(huge)))
    check("read_frame 长帧解出内容", payload == huge)

    # 分片：recv_message 应把 CONT 帧拼成一条完整消息
    stream = io.BytesIO(
        client_frame(b"abc", fin=False)
        + client_frame(b"def", opcode=ws_bridge.OP_CONT, fin=False)
        + client_frame(b"ghi", opcode=ws_bridge.OP_CONT, fin=True)
    )
    client = ws_bridge.WSClient(stream, io.BytesIO())
    op, payload = client.recv_message()
    check("recv_message 分片拼接", op == ws_bridge.OP_TEXT and payload == b"abcdefghi", f"got {op} {payload}")

    # ping -> 应自动回 pong，然后继续读下一条文本
    sink = io.BytesIO()
    stream2 = io.BytesIO(client_frame(b"", opcode=ws_bridge.OP_PING) + client_frame(b"after-ping"))
    client2 = ws_bridge.WSClient(stream2, sink)
    op, payload = client2.recv_message()
    check("ping 自动回 pong", op == ws_bridge.OP_TEXT and payload == b"after-ping", f"got {op} {payload}")
    check("pong 帧已写出", sink.getvalue()[:1] == b"\x8a", f"got {sink.getvalue()[:2]!r}")

    # close 帧
    client3 = ws_bridge.WSClient(io.BytesIO(client_frame(b"", opcode=ws_bridge.OP_CLOSE)), io.BytesIO())
    op, _ = client3.recv_message()
    check("close 帧返回 OP_CLOSE", op == ws_bridge.OP_CLOSE, f"got {op}")

    # 空 payload
    fin, op, payload = ws_bridge.read_frame(io.BytesIO(client_frame(b"")))
    check("read_frame 空帧", payload == b"")


# --------------------------------------------------------------------------- #
# 2) 端到端
# --------------------------------------------------------------------------- #
def call(port: int, path: str, payload: dict | None = None, method: str | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"}, method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_end_to_end() -> None:
    print("[2] 端到端（Node WebSocket 客户端）")

    httpd, port = run_server(0)
    proc = None
    try:
        # 先确认未连接时的行为
        st, res = call(port, "/api/bridge/pick", {})
        check("无扩展时 pick 返回可读错误", res.get("ok") is False and "扩展" in (res.get("error") or ""),
              f"got {res}")

        st, res = call(port, "/api/health", method="GET")
        check("health 带 bridge 状态", "bridge" in res and res["bridge"]["clients"] == 0, f"got {res}")

        # 启动 Node 客户端
        probe = os.path.join(ROOT, "tools", "ws_client_probe.js")
        proc = subprocess.Popen(
            [NODE, probe, f"ws://127.0.0.1:{port}/ws"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )

        # 等待 ready
        ready = False
        deadline = time.time() + 20
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            try:
                msg = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if msg.get("event") == "ready":
                ready = True
                break
            if msg.get("event") == "error":
                check("客户端连接就绪", False, msg.get("message"))
                return
        check("客户端连接并完成 hello", ready)
        if not ready:
            return

        # 等一小会儿让 Hub 完成登记
        time.sleep(0.2)
        st, res = call(port, "/api/health", method="GET")
        check("Hub 已登记扩展", res["bridge"]["extensions"] == 1, f"got {res['bridge']}")

        # 触发抓取
        st, res = call(port, "/api/bridge/pick", {})
        check("pick 已推送给扩展", res.get("ok") is True and res.get("sent", 0) >= 1, f"got {res}")

        # 等待 done
        done = False
        deadline = time.time() + 20
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            try:
                msg = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if msg.get("event") == "done":
                done = True
                check("扩展收到 start-pick 并回传 picked", "start-pick" in msg.get("seen", []),
                      f"seen={msg.get('seen')}")
                break
            if msg.get("event") == "error":
                check("扩展完成抓取回传", False, msg.get("message"))
                break
        check("客户端流程完成", done)

        # 校验桌面版收到 picked
        time.sleep(0.3)
        last = ws_bridge.HUB.last_pick or {}
        check("桌面版收到 picked 负载", last.get("xpath") == "//button[@id='login-btn']", f"got {last}")

        st, res = call(port, "/api/bridge/last", method="GET")
        check("GET /api/bridge/last 可读到结果", (res.get("payload") or {}).get("tag") == "button", f"got {res}")

        # HTTP 兜底通道
        st, res = call(port, "/api/bridge/result", {"payload": {"tag": "a", "xpath": "//a"}})
        check("HTTP 兜底回传生效", res.get("ok") is True and (ws_bridge.HUB.last_pick or {}).get("tag") == "a")
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()
        httpd.shutdown()


def main() -> int:
    test_frames()
    test_end_to_end()
    print("\n" + "=" * 62)
    if fail_count:
        print(f" 结果：{ok_count} 通过 / {fail_count} 失败 ❌")
        return 1
    print(f" 结果：全部 {ok_count} 项通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
