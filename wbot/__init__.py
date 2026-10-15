"""wbot：独立实现的 Python 自动化库，使用 XPath Studio 的元素与浏览器桥。"""
from time import sleep
from . import web, selector, files, folders, strings, regex, json, csv, xzip, request, excel, logging, process
from .elements import ElementLibrary
from .selector import Selector, SelectorStore

__version__ = "0.1.0"
__all__ = ["web", "selector", "files", "folders", "strings", "regex", "json", "csv",
           "xzip", "request", "excel", "logging", "process",
           "ElementLibrary", "Selector", "SelectorStore", "sleep"]
