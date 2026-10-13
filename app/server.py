"""本地 HTTP 服务：静态页面 + JSON API。

纯标准库实现（http.server），便于 PyInstaller 打包，无需额外 Web 框架。
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import ai_client, extension_installer, ws_bridge, xpath_engine

# --------------------------------------------------------------------------- #
# 资源路径（兼容 PyInstaller 打包后的 _MEIPASS）
# --------------------------------------------------------------------------- #
def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    return base / "web"


WEB_DIR = resource_dir()

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


# --------------------------------------------------------------------------- #
# 本地配置（供浏览器扩展桥接时复用 AI 设置）
# --------------------------------------------------------------------------- #
CONFIG_PATH = Path.home() / ".xpath_studio" / "config.json"


def load_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 文档缓存：token -> (root, index)
# --------------------------------------------------------------------------- #
class DocStore:
    def __init__(self, max_items: int = 8) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, tuple[Any, dict[int, int], list]] = {}
        self._order: list[str] = []
        self._max = max_items

    def put(self, root, index, elements) -> str:
        token = secrets.token_urlsafe(12)
        with self._lock:
            self._data[token] = (root, index, elements)
            self._order.append(token)
            while len(self._order) > self._max:
                old = self._order.pop(0)
                self._data.pop(old, None)
        return token

    def get(self, token: str):
        with self._lock:
            return self._data.get(token or "")


DOCS = DocStore()


# --------------------------------------------------------------------------- #
# 抓取远程页面
# --------------------------------------------------------------------------- #
def fetch_url(url: str, timeout: int = 20) -> str:
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# 请求处理
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "XPathStudio/1.0"

    def log_message(self, fmt, *args):  # 静音默认日志
        pass

    # ---- 工具方法 ----
    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200,
                    cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _serve_policy_update_xml(self) -> None:
        """策略里的 update_url 指向这里 —— 桌面版自己就是那个更新服务。"""
        try:
            xml, _crx, _eid = extension_installer.policy_artifacts(self._server_port())
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        self._send_bytes(xml.encode("utf-8"), "text/xml; charset=utf-8", cache="no-cache")

    def _serve_policy_crx(self) -> None:
        """策略首次生效时浏览器会来拉这个 CRX。"""
        try:
            _xml, blob, _eid = extension_installer.policy_artifacts(self._server_port())
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        self._send_bytes(blob, "application/x-chrome-extension", cache="no-cache")

    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        rel = path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._send_json({"error": "非法路径"}, 403)
            return
        if not target.is_file():
            self._send_json({"error": "未找到资源: " + rel}, 404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(target.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ---- WebSocket 桥接 ----
    def _handle_ws(self) -> None:
        """把当前连接升级为 WebSocket，然后交给 ws_bridge 收发。"""
        key = (self.headers.get("Sec-WebSocket-Key") or "").strip()
        upgrade = (self.headers.get("Upgrade") or "").strip().lower()
        if not key or upgrade != "websocket":
            self._send_json({"ok": False, "error": "需要 WebSocket 升级请求"}, 400)
            return
        accept = ws_bridge.accept_key(key)
        try:
            self.wfile.write(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: " + accept.encode("ascii") + b"\r\n\r\n"
            )
            self.wfile.flush()
        except Exception:  # noqa: BLE001
            return
        # 握手完成后这条连接不再走 HTTP 语义
        self.close_connection = True
        ws_bridge.serve(self.rfile, self.wfile)

    # ---- 路由 ----
    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/ws":
            self._handle_ws()
            return
        if path == "/api/health":
            self._send_json({"ok": True, "version": "1.0", "bridge": ws_bridge.HUB.stats()})
            return
        if path == "/api/bridge/last":
            self._send_json({"ok": True, "payload": ws_bridge.HUB.last_pick})
            return
        if path == "/api/extension/browsers":
            self.api_extension_browsers()
            return
        if path == "/extension/update.xml":
            self._serve_policy_update_xml()
            return
        if path == "/extension/extension.crx":
            self._serve_policy_crx()
            return
        if path == "/api/config":
            cfg = load_config()
            safe = dict(cfg)
            if safe.get("apiKey"):
                safe["apiKey"] = "***"
            safe["configured"] = bool(cfg.get("apiKey") and cfg.get("baseUrl"))
            self._send_json({"ok": True, "config": safe})
            return
        self._serve_static(path)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        body = self._read_json()
        try:
            handler = {
                "/api/parse": self.api_parse,
                "/api/validate": self.api_validate,
                "/api/gen": self.api_gen,
                "/api/nl": self.api_nl,
                "/api/fetch": self.api_fetch,
                "/api/scan": self.api_scan,
                "/api/verify": self.api_verify,
                "/api/config": self.api_save_config,
                "/api/bridge/pick": self.api_bridge_pick,
                "/api/bridge/stop": self.api_bridge_stop,
                "/api/bridge/result": self.api_bridge_result,
                "/api/bridge/validate": self.api_bridge_validate,
                "/api/extension/install": self.api_extension_install,
                "/api/extension/open-folder": self.api_extension_open_folder,
                "/api/extension/policy-status": self.api_extension_policy_status,
                "/api/extension/policy-remove": self.api_extension_policy_remove,
                "/api/ai": self.api_ai,
                "/api/ai/test": self.api_ai_test,
            }.get(path)
            if handler is None:
                self._send_json({"error": f"未知接口: {path}"}, 404)
                return
            handler(body)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    # ---- 各接口实现 ----
    def api_parse(self, body):
        html = body.get("html", "")
        root, index, tree, count, elements = xpath_engine.load(html)
        token = DOCS.put(root, index, elements)
        self._send_json(
            {
                "ok": True,
                "token": token,
                "tree": tree,
                "count": count,
                "desc": xpath_engine.describe(root),
            }
        )

    def api_validate(self, body):
        doc = DOCS.get(body.get("token", ""))
        if doc is None:
            self._send_json({"ok": False, "error": "文档已失效，请重新解析"}, 200)
            return
        root, index, _elements = doc
        result = xpath_engine.validate(root, index, body.get("xpath", ""))
        result["ok"] = True
        self._send_json(result)

    def api_gen(self, body):
        doc = DOCS.get(body.get("token", ""))
        if doc is None:
            self._send_json({"ok": False, "error": "文档已失效，请重新解析"}, 200)
            return
        root, index, elements = doc
        idx = body.get("idx")
        target = None
        if isinstance(idx, int) and 0 <= idx < len(elements):
            target = elements[idx]
        if target is None:
            self._send_json({"ok": False, "error": "未找到该节点"}, 200)
            return
        result = xpath_engine.gen_for_element(root, target, index)
        result["ok"] = True
        self._send_json(result)

    def api_nl(self, body):
        doc = DOCS.get(body.get("token", ""))
        if doc is None:
            self._send_json({"ok": False, "error": "文档已失效，请重新解析"}, 200)
            return
        root, index, _elements = doc
        result = xpath_engine.nl_search(root, index, body.get("query", ""))
        result["ok"] = True
        self._send_json(result)

    def api_scan(self, body):
        doc = DOCS.get(body.get("token", ""))
        if doc is None:
            self._send_json({"ok": False, "error": "文档已失效，请重新解析"}, 200)
            return
        root, index, _elements = doc
        result = xpath_engine.scan_page(root, index)
        result["ok"] = True
        self._send_json(result)

    def api_verify(self, body):
        doc = DOCS.get(body.get("token", ""))
        if doc is None:
            self._send_json({"ok": False, "error": "文档已失效，请重新解析"}, 200)
            return
        root, index, _elements = doc
        raw = body.get("selectors", "")
        selectors = raw if isinstance(raw, list) else str(raw).splitlines()
        result = xpath_engine.verify_batch(root, index, selectors)
        result["ok"] = True
        self._send_json(result)

    def api_fetch(self, body):
        url = (body.get("url") or "").strip()
        if not url:
            self._send_json({"ok": False, "error": "请输入网址"}, 200)
            return
        try:
            html = fetch_url(url)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"抓取失败：{exc}"}, 200)
            return
        self._send_json({"ok": True, "html": html, "length": len(html)})

    def api_save_config(self, body):
        patch = body.get("config") or {}
        cur = load_config()
        # 合并写入，避免局部保存时把未提交的字段（如 baseUrl）清空
        cfg = dict(cur)
        cfg.update(patch)
        # 前端传 "***" 表示「保持原 Key 不变」
        if patch.get("apiKey") == "***":
            cfg["apiKey"] = cur.get("apiKey", "")
        save_config(cfg)
        self._send_json({"ok": True, "path": str(CONFIG_PATH)})

    # ---- 浏览器扩展桥接（桌面版 -> 扩展）----
    def api_bridge_pick(self, body):
        """让浏览器扩展进入拾取模式。"""
        stats = ws_bridge.HUB.stats()
        if not stats["extensions"]:
            self._send_json({
                "ok": False,
                "error": "没有已连接的浏览器扩展。请先安装扩展并打开任意网页（扩展会通过 WebSocket 连到本机服务）。",
                "stats": stats,
            }, 200)
            return
        sent = ws_bridge.HUB.broadcast({
            "type": "start-pick",
            "hint": "把鼠标移到目标元素上，按住 Ctrl 再左键点击",
        })
        self._send_json({"ok": sent > 0, "sent": sent, "stats": ws_bridge.HUB.stats()}, 200)

    def api_bridge_stop(self, body):
        sent = ws_bridge.HUB.broadcast({"type": "stop-pick"})
        self._send_json({"ok": True, "sent": sent, "stats": ws_bridge.HUB.stats()}, 200)

    def api_bridge_result(self, body):
        """扩展回传抓取结果。WS 不可用时的 HTTP 兜底通道。"""
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
        ws_bridge.HUB.set_pick(payload)
        ws_bridge.HUB.broadcast({"type": "picked", "payload": payload})
        self._send_json({"ok": True}, 200)

    def api_bridge_validate(self, body):
        result = ws_bridge.HUB.request_browser(body.get("target"), body.get("action", "validate"),
                                              body.get("xpath", ""))
        self._send_json(result)

    # ---- 浏览器扩展一键安装 ----
    def _server_port(self) -> int:
        try:
            return int(self.server.server_address[1])
        except Exception:  # noqa: BLE001
            return 8790

    def api_extension_browsers(self):
        """列出本机浏览器 + 每个浏览器的推荐安装策略 + 扩展目录。"""
        try:
            browsers = extension_installer.find_browsers()
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 200)
            return
        port = self._server_port()
        try:
            ext_dir = str(extension_installer.stable_extension_dir(port))
            dir_error = ""
        except Exception as exc:  # noqa: BLE001
            ext_dir = ""
            dir_error = str(exc)
        rec = extension_installer.pick_browser(browsers)
        self._send_json({
            "ok": True,
            "browsers": browsers,
            "recommendKey": rec["key"] if rec else "",
            "extDir": ext_dir,
            "dirError": dir_error,
            "port": port,
            "platform": extension_installer.platform.system(),
            "connected": ws_bridge.HUB.stats().get("extensions", 0),
            "stats": ws_bridge.HUB.stats(),
        }, 200)

    def api_extension_install(self, body):
        """默认引导安装到现有浏览器；高级策略可用 strategy/browser 覆盖。"""
        strategy = (body.get("strategy") or "auto").strip()
        browser_key = (body.get("browser") or "").strip()
        try:
            timeout = float(body.get("timeout") or 30)
        except Exception:  # noqa: BLE001
            timeout = 30.0
        result = extension_installer.install(
            strategy=strategy,
            browser_key=browser_key,
            port=self._server_port(),
            verify_timeout=max(5.0, min(timeout, 120.0)),
        )
        result["stats"] = ws_bridge.HUB.stats()
        self._send_json(result, 200)

    def api_extension_open_folder(self, body):
        """在资源管理器里打开扩展目录（引导安装时的兜底动作）。"""
        port = self._server_port()
        try:
            ext_dir = extension_installer.stable_extension_dir(port)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)}, 200)
            return
        ok = False
        try:
            if os.name == "nt":
                os.startfile(str(ext_dir))  # type: ignore[attr-defined]
                ok = True
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(ext_dir)])
                ok = True
            else:
                subprocess.Popen(["xdg-open", str(ext_dir)])
                ok = True
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc), "path": str(ext_dir)}, 200)
            return
        self._send_json({"ok": ok, "path": str(ext_dir)}, 200)

    def api_extension_policy_status(self, body):
        """查询企业策略强制安装的状态（只读，不改注册表）。"""
        try:
            res = extension_installer.policy_status(body.get("browser", ""))
            self._send_json({"ok": True, **res}, 200)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 200)

    def api_extension_policy_remove(self, body):
        """卸载企业策略（只删本扩展的条目，保留用户其他策略）。"""
        try:
            res = extension_installer.uninstall_policy(body.get("browser", ""))
            self._send_json(res, 200)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 200)

    def api_ai_test(self, body):
        cfg = body.get("config") or load_config()
        try:
            reply = ai_client.chat(
                cfg.get("baseUrl", ""),
                cfg.get("apiKey", ""),
                cfg.get("model", ""),
                [{"role": "user", "content": "只回复两个字：可用"}],
                timeout=30,
            )
            self._send_json({"ok": True, "reply": (reply or "").strip()[:50]})
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)}, 200)

    def api_ai(self, body):
        cfg = body.get("config") or load_config()
        instruction = body.get("instruction", "")
        html = body.get("html", "")
        if not html:
            doc = DOCS.get(body.get("token", ""))
            if doc is None:
                self._send_json({"ok": False, "error": "文档已失效，请重新解析"}, 200)
                return
            root, _index, _elements = doc
            from lxml import etree

            html = etree.tostring(root, encoding="unicode")
        try:
            result = ai_client.generate_xpath(cfg, html, instruction)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)}, 200)
            return

        # 顺带用本地引擎校验 AI 给出的 xpath
        doc = DOCS.get(body.get("token", ""))
        if doc is not None and result.get("xpath"):
            root, index, _elements = doc
            result["validation"] = xpath_engine.validate(root, index, result["xpath"])
        result["ok"] = True
        self._send_json(result)


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #
def create_server(port: int = 0) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    # WebSocket 是长连接，关服时不要等待这些线程，否则会卡住
    httpd.block_on_close = False
    return httpd


def run_server(port: int = 0):
    httpd = create_server(port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]
