"""wbot 网页自动化：连接 XPath Studio 已抓取的页面。"""
from .browser import BridgeClient, Browser, WebBrowser
from .element import Element, WebElement
from ..errors import StaleTargetError, UnsupportedFeatureError

__all__ = ["attach", "get", "get_active", "create", "WebBrowser", "Browser", "WebElement", "Element"]


def attach(base_url="http://127.0.0.1:8790", *, http_timeout=10):
    """连接最近一次抓取来源；每次调用重新读取当前 documentId。"""
    client = BridgeClient(base_url, http_timeout=http_timeout)
    payload = client.request("/api/bridge/last").get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("frame"), dict):
        raise StaleTargetError("尚无网页抓取结果，请先在 XPath Studio 点击抓取元素")
    target = dict(payload["frame"])
    target["browserId"] = payload.get("browserId")
    return WebBrowser(client, target, url=target.get("url") or payload.get("url", ""),
                      title=payload.get("title", ""))


def get(title=None, url=None, mode="bridge", *, base_url="http://127.0.0.1:8790", http_timeout=10):
    """读取当前抓取目标，可用精确 title/url 限定；不切换用户标签页。"""
    if mode != "bridge":
        raise UnsupportedFeatureError("目前支持 mode='bridge'；不提供 ShadowBot 的 CEF/IE 私有运行时")
    browser = attach(base_url, http_timeout=http_timeout)
    if title is not None and title != browser.title:
        raise StaleTargetError("抓取页面的标题不符合指定 title")
    if url is not None and url != browser.url:
        raise StaleTargetError("抓取页面的 URL 不符合指定 url")
    return browser


get_active = get


def create(url="about:blank", *, headless=True, channel=None, executable_path=None, load_timeout=20):
    """启动独立 Chromium；需要 pip install 'wbot[web]' 及 Playwright 浏览器。"""
    from .playwright_backend import create_browser
    return create_browser(url, headless=headless, channel=channel,
                          executable_path=executable_path, load_timeout=load_timeout)
