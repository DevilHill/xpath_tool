"""基于 urllib 的 HTTP 客户端，TLS 验证保持开启。"""
from dataclasses import dataclass
from email.message import Message
import json as _json
from pathlib import PurePosixPath
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, urlunsplit, unquote
from urllib.request import Request, urlopen
from . import files

_UNSET = object()


@dataclass
class Response:
    status_code: int
    headers: Message
    content: bytes
    url: str
    reason: str = ""

    @property
    def status(self):
        return self.status_code

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    @property
    def text(self):
        return self.content.decode(self.headers.get_content_charset() or "utf-8", errors="replace")

    def json(self):
        return _json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(self.url, self.status_code, self.reason, self.headers, None)
        return self


def send(method, url, *, headers=None, body=None, connect_timeout=30, save_filename=None,
         json=_UNSET, params=None, timeout=None, overwrite=False, max_bytes=64 * 1024 * 1024,
         total_timeout=None):
    """发送 HTTP 请求。4xx/5xx 返回 Response；网络错误直接抛出。

    connect_timeout/timeout 约束套接字操作，total_timeout 在分块读取间检查。
    body 的 dict 按表单编码，json 参数按 JSON 编码；两者不能同时提供。
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("url 必须为 http 或 https 地址")
    if parts.username is not None or parts.password is not None:
        raise ValueError("请通过 Authorization 请求头提供认证，不要嵌入 URL")
    effective_timeout = connect_timeout if timeout is None else timeout
    if effective_timeout <= 0 or max_bytes <= 0 or (total_timeout is not None and total_timeout <= 0):
        raise ValueError("超时时间与 max_bytes 必须为正数")
    if params:
        query = urlencode(params, doseq=True)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query + ("&" if parts.query else "") + query, parts.fragment))
    request_headers = dict(headers or {})
    has_content_type = any(key.lower() == "content-type" for key in request_headers)
    if json is not _UNSET:
        if body is not None:
            raise ValueError("body 与 json 不能同时提供")
        body = _json.dumps(json, ensure_ascii=False).encode("utf-8")
        if not has_content_type:
            request_headers["Content-Type"] = "application/json; charset=utf-8"
    elif isinstance(body, dict):
        body = urlencode(body, doseq=True).encode("utf-8")
        if not has_content_type:
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif isinstance(body, str):
        body = body.encode("utf-8")
    if body is not None and not isinstance(body, bytes):
        raise TypeError("body 必须是 str、bytes、dict 或 None")
    req = Request(url, data=body, headers=request_headers, method=method.upper())
    started = time.monotonic()
    try:
        raw = urlopen(req, timeout=effective_timeout)
    except HTTPError as error:
        raw = error
    with raw:
        chunks, size = [], 0
        while True:
            if total_timeout is not None and time.monotonic() - started > total_timeout:
                raise TimeoutError("HTTP 响应读取总时间超限")
            block = raw.read(min(65536, max_bytes - size + 1))
            if not block:
                break
            size += len(block)
            if size > max_bytes:
                raise ValueError("HTTP 响应超过 max_bytes")
            chunks.append(block)
        response = Response(raw.status, raw.headers, b"".join(chunks), raw.url, str(raw.reason))
    if save_filename is not None:
        response.raise_for_status()
        files.write_bytes(save_filename, response.content, overwrite=overwrite)
    return response


def get(url, **kwargs):
    return send("GET", url, **kwargs)


def post(url, **kwargs):
    return send("POST", url, **kwargs)


def put(url, **kwargs):
    return send("PUT", url, **kwargs)


def patch(url, **kwargs):
    return send("PATCH", url, **kwargs)


def delete(url, **kwargs):
    return send("DELETE", url, **kwargs)


def head(url, **kwargs):
    return send("HEAD", url, **kwargs)


def download(url, save_filename, *, connect_timeout=30, wait_complete_timeout=300, overwrite=False, max_bytes=64 * 1024 * 1024):
    return send("GET", url, connect_timeout=connect_timeout, total_timeout=wait_complete_timeout,
                save_filename=save_filename, overwrite=overwrite, max_bytes=max_bytes)


def extract_filename(url):
    # URL 的文件名必须保持为单一文件名，解码后拒绝路径与设备名。
    path = urlsplit(url).path
    name = unquote(PurePosixPath(path).name)
    devices = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if not name or path.endswith("/") or name in (".", "..") or name.endswith((".", " ")) or name.split(".")[0].upper() in devices or any(c in name for c in '/\\:\x00'):
        raise ValueError("URL 中没有安全的文件名")
    return name
