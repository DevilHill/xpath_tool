"""通过 XPath Studio 的本机桥访问已抓取网页；不依赖桌面应用包。"""
from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..errors import (AmbiguousElementError, BridgeConnectionError,
    ElementNotFoundError, ElementNotInteractableError, InvalidSelectorError,
    StaleTargetError, UnsupportedFeatureError, WbotError, WbotTimeoutError)


def _seconds(value, name="timeout"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} 必须是非负有限秒数")
    return float(value)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BridgeConnectionError("本机桥不接受 HTTP 重定向")


class BridgeClient:
    def __init__(self, base_url="http://127.0.0.1:8790", *, http_timeout=10):
        if not isinstance(base_url, str):
            raise ValueError("base_url 必须是本机 HTTP 地址")
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or
                parsed.username or parsed.password or parsed.path not in ("", "/") or
                parsed.query or parsed.fragment):
            raise ValueError("仅允许 http://127.0.0.1:端口 的 XPath Studio 本机桥")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("无效的桥端口") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("无效的桥端口")
        self.base_url = base_url.rstrip("/")
        self.http_timeout = _seconds(http_timeout, "http_timeout")
        if not self.http_timeout:
            raise ValueError("http_timeout 必须大于零")
        # 不将本地网页自动化请求发送给系统代理，也不跟随外部跳转。
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def request(self, path, data=None):
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        request = Request(self.base_url + path, body, {"Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=self.http_timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except HTTPError as exc:
            raw = exc.read(1024 * 1024)
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise BridgeConnectionError(f"本机桥 HTTP {exc.code}，请检查 XPath Studio 版本") from exc
            if isinstance(payload, dict) and payload.get("ok") is False:
                self._raise(payload)
            raise BridgeConnectionError(f"本机桥 HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise BridgeConnectionError(f"无法连接 {self.base_url}：{exc}；请启动 XPath Studio 并连接扩展") from exc
        if len(raw) > 4 * 1024 * 1024:
            raise BridgeConnectionError("本机桥响应超过 4 MiB")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise BridgeConnectionError("本机桥未返回有效 JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            raise BridgeConnectionError("本机桥响应缺少 ok 字段")
        if not payload["ok"]:
            self._raise(payload)
        return payload

    @staticmethod
    def _raise(payload):
        error_type = {"not_found": ElementNotFoundError, "ambiguous": AmbiguousElementError,
            "invalid_selector": InvalidSelectorError, "not_interactable": ElementNotInteractableError,
            "stale_target": StaleTargetError, "disconnected": BridgeConnectionError,
            "timeout": BridgeConnectionError}.get(payload.get("code"), WbotError)
        raise error_type(str(payload.get("error") or "网页操作失败"))


class WebBrowser:
    """绑定一次抓取的 documentId；导航后显式重新 attach。"""
    def __init__(self, client, target, *, url="", title=""):
        if (not isinstance(target, dict) or not target.get("browserId") or not target.get("documentId") or
                type(target.get("tabId")) is not int or type(target.get("frameId")) is not int or
                target["tabId"] < 0 or target["frameId"] < 0):
            raise StaleTargetError("抓取来源不完整，请在 XPath Studio 重新抓取网页元素")
        self._client = client
        self._target = deepcopy(target)
        self.url = str(url or target.get("url") or "")
        self.title = str(title or "")

    @property
    def target(self):
        return deepcopy(self._target)

    def _selector(self, selector):
        record = selector if isinstance(selector, dict) else None
        if isinstance(selector, str):
            xpath, frame, url = selector, {}, ""
        else:
            xpath = record.get("xpath") if record is not None else getattr(selector, "xpath", None)
            if callable(xpath):
                xpath = xpath()
            frame = record.get("frame", {}) if record is not None else getattr(selector, "frame", {})
            url = record.get("url", "") if record is not None else getattr(selector, "url", "")
        if not isinstance(xpath, str) or not xpath.strip() or len(xpath) > 16384:
            raise InvalidSelectorError("需要非空 XPath 字符串或含 xpath 的 SelectorRecord")
        if frame and not isinstance(frame, dict):
            raise InvalidSelectorError("frame 必须是框架元数据字典")
        frame = frame or {}
        # 持久化记录的 documentId 不能用于下一次运行；这里只比较网页/框架作用域。
        saved_url = frame.get("url") or url
        actual_url = self._target.get("url") or self.url
        if saved_url and actual_url and saved_url != actual_url:
            raise StaleTargetError(f"元素库网页与当前抓取网页不符：{saved_url} != {actual_url}")
        for field in ("frameId", "isTop", "xpathScope", "topUrl"):
            if field in frame and field in self._target and frame[field] != self._target[field]:
                raise StaleTargetError(f"元素库的 {field} 与当前抓取框架不符，请重新抓取对应框架")
        return xpath.strip()

    def _command(self, action, xpath, **options):
        payload = self._client.request("/api/wbot/command", {
            "target": self.target, "action": action, "xpath": xpath, "options": options})
        if "result" not in payload:
            raise BridgeConnectionError("本机桥响应缺少 result 字段")
        return payload["result"]

    def _element_token(self):
        return self._target["documentId"]

    def _element_command(self, token, action, xpath, **options):
        if token != self._element_token():
            raise StaleTargetError("元素所属文档已导航，请重新定位")
        return self._command(action, xpath, **options)

    def _query(self, xpath):
        result = self._command("query", xpath, strict=False)
        if (not isinstance(result, dict) or type(result.get("count")) is not int or result["count"] < 0):
            raise BridgeConnectionError("本机桥 query 返回了无效 count")
        return result

    def find(self, selector, *, timeout=20):
        from .element import WebElement
        xpath = self._selector(selector)
        deadline = time.monotonic() + _seconds(timeout)
        while True:
            count = self._query(xpath)["count"]
            if count > 1:
                raise AmbiguousElementError(f"XPath 匹配 {count} 个元素，请使用 find_all 明确选择")
            if count == 1:
                return WebElement(self, xpath, strict=True)
            if time.monotonic() >= deadline:
                raise ElementNotFoundError(f"{timeout} 秒内未找到元素：{xpath}")
            time.sleep(min(.1, max(0, deadline - time.monotonic())))

    def find_all(self, selector, *, timeout=20):
        from .element import WebElement
        xpath = self._selector(selector)
        deadline = time.monotonic() + _seconds(timeout)
        while True:
            count = self._query(xpath)["count"]
            if count > 500:
                raise WbotError(f"XPath 匹配 {count} 个元素，超过 500 个上限，请缩小 XPath 范围")
            if count:
                return [WebElement(self, xpath, index=i, strict=False) for i in range(count)]
            if time.monotonic() >= deadline:
                return []
            time.sleep(min(.1, max(0, deadline - time.monotonic())))

    find_by_xpath = find
    find_all_by_xpath = find_all

    def count(self, selector):
        return self._query(self._selector(selector))["count"]

    def exists(self, selector):
        return self.count(selector) > 0

    def wait_appear(self, selector, timeout=20):
        try:
            self.find(selector, timeout=timeout)
            return True
        except ElementNotFoundError:
            return False

    def wait_disappear(self, selector, timeout=20):
        xpath = self._selector(selector)
        deadline = time.monotonic() + _seconds(timeout)
        while True:
            if self._query(xpath)["count"] == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(.1, max(0, deadline - time.monotonic())))

    def is_element_displayed(self, selector):
        try:
            return self.find(selector, timeout=0).is_visible()
        except ElementNotFoundError:
            return False

    def get_url(self):
        """返回抓取时记录的框架 URL；不会声称是导航后的实时 URL。"""
        return self.url

    def get_title(self):
        """返回抓取记录中的标题。"""
        return self.title

    def get_text(self):
        return self.find("//body", timeout=0).get_text()

    def find_by_css(self, *args, **kwargs):
        raise UnsupportedFeatureError("桥后端支持 XPath；请从 XPath Studio 保存 XPath")

    find_all_by_css = find_by_css

    def navigate(self, *args, **kwargs):
        raise UnsupportedFeatureError("桥后端绑定已抓取文档；请在浏览器导航后重新抓取并 attach")

    def execute_javascript(self, *args, **kwargs):
        raise UnsupportedFeatureError("桥后端仅开放受约束的元素操作，不提供任意 JavaScript 执行")

    def close(self):
        """释放 Python 包装对象无需关闭用户浏览器。"""
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


Browser = WebBrowser
