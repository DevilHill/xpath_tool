"""可选 Playwright 后端，延迟导入，不影响纯本机桥用户。"""
from __future__ import annotations

from .browser import WebBrowser, _seconds
from ..errors import (AmbiguousElementError, ElementNotFoundError, InvalidSelectorError,
    ElementNotInteractableError, StaleTargetError, UnsupportedFeatureError,
    WbotError, WbotTimeoutError)


class PlaywrightBrowser(WebBrowser):
    """管理自己创建的浏览器；XPath 作用域为主框架。"""
    def __init__(self, runtime, browser, page):
        self._runtime = runtime
        self._owned_browser = browser
        self.page = page
        self._closed = False
        self._generation = 0
        self.page.on("framenavigated", self._on_navigation)
        super().__init__(None, {"browserId": "playwright", "documentId": "owned",
            "tabId": 0, "frameId": 0, "isTop": True, "xpathScope": "page",
            "url": page.url, "topUrl": page.url}, url=page.url)

    def _on_navigation(self, frame):
        if frame == self.page.main_frame:
            self._generation += 1

    def _element_token(self):
        self._check_open()
        # 一次协议往返处理已发生的导航事件，避免只读本地 generation 的竞态。
        from playwright.sync_api import Error
        try:
            self.page.evaluate("() => location.href")
        except Error as exc:
            raise StaleTargetError("页面正在导航，请等待加载后重新定位") from exc
        return self._generation

    def _element_command(self, token, action, xpath, **options):
        if token != self._element_token():
            raise StaleTargetError("元素所属页面已导航，请重新 find")
        return self._command(action, xpath, _expected_generation=token, **options)

    def _selector(self, selector):
        self._check_open()
        self.url = self.page.url
        self._target.update(url=self.url, topUrl=self.url)
        return super()._selector(selector)

    def _check_open(self):
        if self._closed or self.page.is_closed():
            raise StaleTargetError("wbot 创建的浏览器已关闭")

    def _command(self, action, xpath, **options):
        from playwright.sync_api import Error, TimeoutError as PlaywrightTimeout
        self._check_open()
        locator = self.page.locator("xpath=" + xpath)
        handles = []
        try:
            # 单次 JS 查询确认节点类型，禁止标量/文本/属性 XPath 当作元素。
            result = self.page.evaluate("""xpath => {
                let r;
                try { r=document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); }
                catch(e) { throw new Error('WBOT_INVALID_SELECTOR: '+e.message); }
                const items=[];
                for(let i=0;i<r.snapshotLength;i++) {
                    const e=r.snapshotItem(i);
                    if(e.nodeType!==1) throw new Error('WBOT_NON_ELEMENT');
                    if(i<500) items.push({text:(e.innerText||e.textContent||'').slice(0,2000),
                        tag:e.tagName.toLowerCase(),attributes:Object.fromEntries(Array.from(e.attributes).map(a=>[a.name,a.value]))});
                }
                return {count:r.snapshotLength,items};
            }""", xpath)
            if action == "query":
                return result
            # 绑定真实 DOM 节点，导航或节点替换后不重定向到新页面的同名元素。
            handles = locator.element_handles()
            expected_generation = options.get("_expected_generation", self._generation)
            if expected_generation != self._generation:
                raise StaleTargetError("定位过程中页面已导航，请重新 find")
            count = len(handles)
            index = options.get("index", 0)
            if options.get("strict", True) and count > 1:
                raise AmbiguousElementError(f"XPath 当前匹配 {count} 个元素")
            if count <= index:
                raise ElementNotFoundError("XPath 当前未匹配到指定元素")
            locator = handles[index]
            if action == "text":
                return locator.evaluate("e => e.innerText === undefined ? (e.textContent || '') : e.innerText")
            if action == "attribute":
                if options["name"] == "value":
                    return locator.evaluate("e => 'value' in e ? String(e.value) : e.getAttribute('value')")
                return locator.get_attribute(options["name"])
            if action == "visible":
                return locator.is_visible()
            if action == "enabled":
                return locator.is_enabled()
            if action == "click":
                locator.click(timeout=8000)
            elif action == "input":
                value = options["value"]
                if options.get("append"):
                    value = locator.evaluate("e => 'value' in e ? String(e.value) : (e.textContent || '')") + value
                locator.fill(value, timeout=8000)
            elif action == "check":
                locator.set_checked(options["value"], timeout=8000)
            elif action == "select":
                key = "label" if options.get("mode") == "text" else "value"
                matches = locator.evaluate("""(e, o) => {
                    if(e.tagName!=='SELECT') return -1;
                    return Array.from(e.options).filter(x => (o.mode==='text' ? x.text : x.value)===o.value).length;
                }""", {"mode": options.get("mode"), "value": options["value"]})
                if matches < 0:
                    raise ElementNotInteractableError("目标不是下拉框")
                if matches > 1:
                    raise AmbiguousElementError("多个下拉选项匹配，请使用唯一值")
                if matches == 0:
                    raise ElementNotFoundError("未找到下拉选项")
                locator.select_option(**{key: options["value"]}, timeout=8000)
            elif action == "hover":
                locator.hover(timeout=8000)
            elif action == "scroll":
                locator.scroll_into_view_if_needed(timeout=8000)
            else:
                raise UnsupportedFeatureError(f"不支持的网页动作：{action}")
            return True
        except PlaywrightTimeout as exc:
            raise ElementNotInteractableError(f"元素操作未在 8 秒内完成：{exc}") from exc
        except Error as exc:
            message = str(exc)
            if "strict mode violation" in message:
                raise AmbiguousElementError(message) from exc
            if "XPath" in message or "WBOT_NON_ELEMENT" in message or "WBOT_INVALID_SELECTOR" in message:
                raise InvalidSelectorError(message) from exc
            if self.page.is_closed():
                raise StaleTargetError("浏览器页面已关闭") from exc
            if (options.get("_expected_generation", self._generation) != self._generation or
                    "not attached" in message or "Execution context was destroyed" in message):
                raise StaleTargetError("元素所属文档或节点已失效，请重新 find") from exc
            raise WbotError(message) from exc
        finally:
            for handle in handles:
                try:
                    handle.dispose()
                except Error:
                    pass

    def get_url(self):
        self._check_open()
        return self.page.url

    def get_title(self):
        self._check_open()
        return self.page.title()

    def get_html(self):
        self._check_open()
        return self.page.content()

    def navigate(self, url, *, load_timeout=20):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        self._check_open()
        if not isinstance(url, str) or not url:
            raise ValueError("url 必须是非空字符串")
        timeout = _seconds(load_timeout, "load_timeout")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=max(1, timeout * 1000))
        except PlaywrightTimeout as exc:
            raise WbotTimeoutError(f"网页加载超时：{url}") from exc
        self.url = self.page.url
        self._target.update(url=self.url, topUrl=self.url)

    goto = navigate

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._owned_browser.close()
        finally:
            self._runtime.stop()


def create_browser(url, *, headless=True, channel=None, executable_path=None, load_timeout=20):
    if type(headless) is not bool:
        raise TypeError("headless 必须为布尔值")
    _seconds(load_timeout, "load_timeout")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise UnsupportedFeatureError("独立浏览器后端需要 pip install 'wbot[web]'，然后运行 python -m playwright install chromium；或传 channel='msedge' 使用已安装的 Edge") from exc
    runtime = sync_playwright().start()
    browser = None
    try:
        options = {"headless": headless}
        if channel:
            options["channel"] = channel
        if executable_path:
            options["executable_path"] = str(executable_path)
        browser = runtime.chromium.launch(**options)
        page = browser.new_page()
        result = PlaywrightBrowser(runtime, browser, page)
        result.navigate(url, load_timeout=load_timeout)
        return result
    except Exception:
        try:
            if browser is not None:
                browser.close()
        finally:
            runtime.stop()
        raise
