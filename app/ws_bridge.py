"""极简 WebSocket 服务端（RFC 6455 子集）——只依赖标准库。

用途：桌面版 ⇄ 浏览器扩展 的**双向实时**桥接。

   桌面版点「抓取元素」  --WS-->  {"type":"start-pick"}   扩展进入拾取模式
   扩展 Ctrl+左键选中    --WS-->  {"type":"picked", ...}  桌面版渲染定位器

只实现文本帧 / 分片 / ping / pong / close，足够本场景使用，
且不引入任何第三方依赖（保持 PyInstaller 打包体积与稳定性）。

设计要点：
- 服务端发出的帧**不加掩码**（RFC 规定），客户端发来的帧必须带掩码，读取时解掩码。
- 每个连接跑在 ThreadingHTTPServer 自己的线程里，`serve()` 阻塞直到断开。
- `Hub` 负责登记所有在线客户端并广播，读写都在锁外，避免慢客户端阻塞广播。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time
from typing import Any, Callable
from urllib.parse import urlparse

# RFC 6455 规定的固定 GUID
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

MAX_FRAME = 16 * 1024 * 1024  # 单帧上限，防止异常超大帧


def accept_key(key: str) -> str:
    """由客户端的 Sec-WebSocket-Key 计算 Sec-WebSocket-Accept。"""
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


# --------------------------------------------------------------------------- #
# 帧编解码
# --------------------------------------------------------------------------- #
def encode_frame(payload: bytes, opcode: int = OP_TEXT, mask: bytes | None = None) -> bytes:
    """把 payload 编码成一个「已完成」的帧。

    服务端 -> 客户端：mask=None（RFC 规定不得掩码）。
    客户端 -> 服务端：必须传 4 字节 mask（做 CDP 客户端时用）。
    """
    n = len(payload)
    head = bytearray()
    head.append(0x80 | (opcode & 0x0F))  # FIN=1
    masked = 0x80 if mask is not None else 0x00
    if n < 126:
        head.append(masked | n)
    elif n < 65536:
        head.append(masked | 126)
        head += struct.pack(">H", n)
    else:
        head.append(masked | 127)
        head += struct.pack(">Q", n)
    if mask is not None:
        head += mask
        payload = bytes(payload[i] ^ mask[i % 4] for i in range(n))
    return bytes(head) + payload


def _read_exact(rfile, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = rfile.read(n - len(buf))
        if not chunk:
            raise ConnectionError("连接已关闭")
        buf += chunk
    return bytes(buf)


def read_frame(rfile):
    """读取一个帧，返回 (fin, opcode, payload)；出错返回 (None, None, None)。"""
    try:
        b1, b2 = _read_exact(rfile, 2)
        fin = bool(b1 & 0x80)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", _read_exact(rfile, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _read_exact(rfile, 8))[0]
        if length > MAX_FRAME:
            return None, None, None
        mask = _read_exact(rfile, 4) if masked else b""
        payload = _read_exact(rfile, length) if length else b""
        if masked:
            payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
        return fin, opcode, payload
    except Exception:  # noqa: BLE001
        return None, None, None


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
class WSClient:
    def __init__(self, rfile, wfile) -> None:
        self.rfile = rfile
        self.wfile = wfile
        self.role = "unknown"       # extension / ui / unknown
        self.info: dict[str, Any] = {}
        self.connected_at = time.time()
        self._lock = threading.Lock()
        self.alive = True

    # ---- 发送 ----
    def send_frame(self, payload: bytes, opcode: int = OP_TEXT) -> bool:
        with self._lock:
            if not self.alive:
                return False
            try:
                self.wfile.write(encode_frame(payload, opcode))
                self.wfile.flush()
                return True
            except Exception:  # noqa: BLE001
                self.alive = False
                return False

    def send_json(self, obj: Any) -> bool:
        try:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        except Exception:  # noqa: BLE001
            return False
        return self.send_frame(data, OP_TEXT)

    # ---- 接收 ----
    def recv_message(self):
        """读取一条完整消息（自动拼接分片），返回 (opcode, payload)。

        连接断开返回 (None, None)。文本帧返回 (OP_TEXT, bytes)。
        """
        fragments = bytearray()
        first_op = None
        while True:
            fin, opcode, payload = read_frame(self.rfile)
            if fin is None:
                return None, None

            if opcode == OP_CLOSE:
                return OP_CLOSE, b""
            if opcode == OP_PING:
                self.send_frame(payload, OP_PONG)
                continue
            if opcode == OP_PONG:
                continue

            if opcode == OP_CONT:
                fragments += payload
            else:
                first_op = opcode
                fragments = bytearray(payload)

            if fin:
                return first_op, bytes(fragments)

    def close(self) -> None:
        self.alive = False
        try:
            self.send_frame(b"", OP_CLOSE)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# 广播中心
# --------------------------------------------------------------------------- #
class Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[WSClient] = []
        self.last_pick: dict[str, Any] | None = None
        self.last_pick_at: float = 0.0

    # ---- 登记 ----
    def add(self, client: WSClient) -> None:
        with self._lock:
            self._clients.append(client)

    def remove(self, client: WSClient) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def clients(self) -> list[WSClient]:
        with self._lock:
            return list(self._clients)

    def stats(self) -> dict[str, Any]:
        clients = self.clients()
        return {
            "clients": len(clients),
            "extensions": sum(1 for c in clients if c.role == "extension"),
            "uis": sum(1 for c in clients if c.role == "ui"),
            "lastPickAt": self.last_pick_at,
        }

    # ---- 广播 ----
    def broadcast(self, obj: Any, exclude: WSClient | None = None) -> int:
        """向所有在线客户端推送；返回成功条数。失败的连接会被剔除。"""
        sent = 0
        dead: list[WSClient] = []
        for c in self.clients():
            if c is exclude:
                continue
            if c.send_json(obj):
                sent += 1
            else:
                dead.append(c)
        for c in dead:
            self.remove(c)
        return sent

    def set_pick(self, payload: dict[str, Any]) -> None:
        self.last_pick = payload
        self.last_pick_at = time.time()


HUB = Hub()


# --------------------------------------------------------------------------- #
# 消息分发
# --------------------------------------------------------------------------- #
def _broadcast_stats() -> None:
    HUB.broadcast({"type": "stats", "stats": HUB.stats()})


def handle_message(client: WSClient, msg: dict[str, Any]) -> None:
    kind = msg.get("type")

    if kind == "hello":
        client.role = str(msg.get("role") or "unknown")
        client.info = {k: v for k, v in msg.items() if k not in ("type", "role")}
        _broadcast_stats()
        return

    if kind == "picked":
        payload = msg.get("payload") or {}
        if isinstance(payload, dict):
            HUB.set_pick(payload)
            HUB.broadcast({"type": "picked", "payload": payload}, exclude=client)
        return

    if kind == "status":
        HUB.broadcast({"type": "status", "payload": msg.get("payload")}, exclude=client)
        return

    if kind == "ping":
        client.send_json({"type": "pong"})
        return

    # 其余消息原样转发给其它端（例如桌面版给扩展的自定义指令）
    HUB.broadcast(msg, exclude=client)


# --------------------------------------------------------------------------- #
# 连接主循环
# --------------------------------------------------------------------------- #
def serve(rfile, wfile, on_event: Callable[[str], None] | None = None) -> None:
    """在已握手的连接上跑收发循环，直到断开。"""
    client = WSClient(rfile, wfile)
    HUB.add(client)
    try:
        client.send_json({
            "type": "hello",
            "server": "XPathStudio",
            "version": "1.0",
            "stats": HUB.stats(),
        })
        while True:
            opcode, payload = client.recv_message()
            if opcode is None or opcode == OP_CLOSE:
                break
            if opcode != OP_TEXT:
                continue
            try:
                msg = json.loads(payload.decode("utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(msg, dict):
                handle_message(client, msg)
    except Exception:  # noqa: BLE001
        pass
    finally:
        HUB.remove(client)
        _broadcast_stats()
        if on_event:
            try:
                on_event("disconnect")
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# WebSocket 客户端（用于驱动 Chrome DevTools Protocol）
# --------------------------------------------------------------------------- #
class WSClientConn:
    """最小 WebSocket 客户端：握手 + 收发文本帧。

    客户端发出的帧必须加掩码，因此复用 encode_frame(mask=...)。
    CDP 的消息都很小，不做分片重组。

    **Origin 默认不发**：Chrome 的 DevTools 端点会校验 Origin，
    带了不在白名单里的 Origin 会直接回 ``403 Forbidden``
    （除非启动时给了 ``--remote-allow-origins``）。
    实测 Chrome 153：带 Origin 握手 403，去掉就正常。
    """

    def __init__(self, url: str, timeout: float = 10.0, origin: str | None = None) -> None:
        self.url = url
        self.timeout = timeout
        self.origin = origin
        self.sock: socket.socket | None = None
        self.rfile = None
        self.wfile = None

    def connect(self) -> None:
        u = urlparse(self.url)
        host = u.hostname or "127.0.0.1"
        port = u.port or 80
        path = u.path or "/"
        if u.query:
            path += "?" + u.query

        self.sock = socket.create_connection((host, port), timeout=self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
        )
        if self.origin:
            req += f"Origin: {self.origin}\r\n"
        req += "\r\n"
        self.sock.sendall(req.encode("ascii"))
        self.rfile = self.sock.makefile("rb")

        lines: list[bytes] = []
        while True:
            line = self.rfile.readline()
            if not line:
                raise ConnectionError("WebSocket 握手无响应")
            if line in (b"\r\n", b"\n"):
                break
            lines.append(line)
        status = lines[0].decode("latin-1").strip() if lines else ""
        if "101" not in status:
            raise ConnectionError(f"WebSocket 握手失败：{status}")
        self.wfile = self.sock.makefile("wb")

    def send_json(self, obj: Any) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.wfile.write(encode_frame(data, OP_TEXT, mask=os.urandom(4)))
        self.wfile.flush()

    def recv_json(self):
        """读取下一条 JSON 消息；连接关闭返回 None。"""
        while True:
            fin, opcode, payload = read_frame(self.rfile)
            if fin is None or opcode == OP_CLOSE:
                return None
            if opcode == OP_PING:
                self.wfile.write(encode_frame(payload, OP_PONG, mask=os.urandom(4)))
                self.wfile.flush()
                continue
            if opcode in (OP_TEXT, OP_CONT):
                try:
                    return json.loads(payload.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    continue

    def call(self, method: str, params: dict | None = None, msg_id: int = 1,
             timeout: float = 10.0, session_id: str | None = None):
        """发一条 CDP 命令并等待同 id 的响应。

        ``session_id`` 用于**扁平化**的 CDP 会话（``Target.attachToTarget`` 带
        ``flatten: true`` 时返回）：要把命令发给某个具体 target（例如扩展的
        service worker），就必须带上它，否则命令会被当成浏览器级命令。
        """
        msg = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self.send_json(msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.recv_json()
            if msg is None:
                return None
            if msg.get("id") == msg_id:
                return msg
        return None

    def close(self) -> None:
        for f in (self.rfile, self.wfile):
            try:
                if f is not None:
                    f.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self.sock is not None:
                self.sock.close()
        except Exception:  # noqa: BLE001
            pass
