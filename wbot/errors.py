"""wbot 的稳定异常类型。"""

class WbotError(Exception):
    """所有 wbot 运行错误的基类。"""


class BridgeConnectionError(WbotError):
    """XPath Studio 服务不可达或响应无效。"""


class StaleTargetError(WbotError):
    """原网页或框架已失效，需要重新抓取。"""


class ElementNotFoundError(WbotError):
    """没有匹配到元素。"""


class AmbiguousElementError(WbotError):
    """匹配多个元素，拒绝猜测操作对象。"""


class InvalidSelectorError(WbotError, ValueError):
    """选择器格式或作用域无效。"""


class ElementNotInteractableError(WbotError):
    """元素不能执行请求的操作。"""


class WbotTimeoutError(WbotError, TimeoutError):
    """等待元素状态超时。"""


class UnsupportedFeatureError(WbotError, NotImplementedError):
    """此后端尚未提供请求的能力。"""
