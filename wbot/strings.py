"""常用字符串转换；这是 wbot 新增的工具 API。"""
import base64
import html
import unicodedata
from urllib.parse import quote, unquote


def trim(text, chars=None):
    return text.strip(chars)


def split(text, separator=None, maxsplit=-1):
    return text.split(separator, maxsplit)


def join(values, separator=""):
    return separator.join(str(value) for value in values)


def replace(text, old, new, count=-1):
    return text.replace(old, new, count)


def contains(text, value, *, ignore_case=False):
    return value.casefold() in text.casefold() if ignore_case else value in text


def substring(text, start, length=None):
    if length is not None and length < 0:
        raise ValueError("length 不能为负数")
    return text[start:] if length is None else text[start:start + length]


def normalize(text, form="NFKC"):
    return unicodedata.normalize(form, text)


def base64_encode(text, encoding="utf-8"):
    return base64.b64encode(text.encode(encoding)).decode("ascii")


def base64_decode(text, encoding="utf-8"):
    return base64.b64decode(text, validate=True).decode(encoding)


html_escape = html.escape
html_unescape = html.unescape
url_encode = quote
url_decode = unquote
