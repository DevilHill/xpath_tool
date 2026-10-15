"""按 XPath 重新解析的元素句柄；所有操作在浏览器内再次验证唯一性。"""
from __future__ import annotations

import time
from .browser import _seconds
from ..errors import (AmbiguousElementError, ElementNotFoundError,
    StaleTargetError, UnsupportedFeatureError, WbotTimeoutError)


class WebElement:
    def __init__(self, browser, xpath, *, index=0, strict=True):
        if type(index) is not int or index < 0:
            raise ValueError("index 必须是非负整数")
        if type(strict) is not bool:
            raise ValueError("strict 必须为布尔值")
        self.browser = browser
        self.xpath = browser._selector(xpath)
        self.index = index
        self.strict = strict
        self._token = browser._element_token()

    def _action(self, action, **options):
        return self.browser._element_command(self._token, action, self.xpath,
            index=self.index, strict=self.strict, **options)

    def count(self):
        if self._token != self.browser._element_token():
            raise StaleTargetError("元素所属文档已导航，请重新定位")
        return self.browser._query(self.xpath)["count"]

    def exists(self):
        count = self.count()
        if self.strict and count > 1:
            raise AmbiguousElementError(f"XPath 当前匹配 {count} 个元素")
        return count > self.index

    def click(self, *, button="left", delay_after=0, simulative=False):
        if button != "left" or simulative:
            raise UnsupportedFeatureError("桥后端仅支持 DOM 左键 click，不支持原生鼠标模拟")
        delay = _seconds(delay_after, "delay_after")
        result = self._action("click")
        if delay:
            time.sleep(delay)
        return result

    def input(self, text, *, append=False, delay_after=0, simulative=False):
        if not isinstance(text, str) or type(append) is not bool:
            raise TypeError("text 必须为字符串，append 必须为布尔值")
        if simulative:
            raise UnsupportedFeatureError("桥后端使用 DOM 输入事件，不支持键盘驱动模拟")
        delay = _seconds(delay_after, "delay_after")
        result = self._action("input", value=text, append=append)
        if delay:
            time.sleep(delay)
        return result

    def get_text(self):
        return self._action("text")

    def get_attribute(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("属性名不能为空")
        return self._action("attribute", name=name)

    def get_value(self):
        # bridge attribute 的 value 特例返回 DOM 当前值，而非初始 HTML 属性。
        return self.get_attribute("value")

    def set_value(self, value):
        return self.input(value)

    def is_visible(self):
        try:
            return self._action("visible")
        except ElementNotFoundError:
            return False

    is_displayed = is_visible

    def is_enabled(self):
        return self._action("enabled")

    def select(self, item, *, mode="value", delay_after=0):
        if not isinstance(item, str):
            raise TypeError("item 必须为字符串")
        if mode not in ("value", "text"):
            raise UnsupportedFeatureError("select 支持精确 value 或 text，不进行模糊猜测")
        delay = _seconds(delay_after, "delay_after")
        result = self._action("select", value=item, mode=mode)
        if delay:
            time.sleep(delay)
        return result

    def check(self, mode="check", delay_after=0):
        if mode not in ("check", "uncheck"):
            raise ValueError("mode 必须为 check 或 uncheck")
        delay = _seconds(delay_after, "delay_after")
        result = self._action("check", value=mode == "check")
        if delay:
            time.sleep(delay)
        return result

    def hover(self):
        return self._action("hover")

    def scroll_into_view(self):
        return self._action("scroll")

    def wait(self, state="visible", *, timeout=20):
        if state not in ("visible", "hidden", "attached", "detached", "enabled"):
            raise ValueError("state 必须为 visible/hidden/attached/detached/enabled")
        deadline = time.monotonic() + _seconds(timeout)
        while True:
            try:
                if state in ("attached", "detached"):
                    value = self.exists()
                    ready = value if state == "attached" else not value
                elif state == "enabled":
                    ready = self.is_enabled()
                else:
                    value = self.is_visible()
                    ready = value if state == "visible" else not value
            except ElementNotFoundError:
                ready = state in ("hidden", "detached")
            if ready:
                return self
            if time.monotonic() >= deadline:
                raise WbotTimeoutError(f"等待元素 {state} 超时（{timeout} 秒）：{self.xpath}")
            time.sleep(min(.1, max(0, deadline - time.monotonic())))


Element = WebElement
