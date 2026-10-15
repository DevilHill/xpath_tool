"""正则表达式包装，参数顺序保持 Python re 习惯。"""
import re

IGNORECASE = re.IGNORECASE
MULTILINE = re.MULTILINE
DOTALL = re.DOTALL
compile = re.compile
escape = re.escape


def findall(pattern, text, *, flags=0):
    return re.findall(pattern, text, flags)


def search(pattern, text, *, flags=0):
    return re.search(pattern, text, flags)


def match(pattern, text, *, flags=0):
    return re.match(pattern, text, flags)


def fullmatch(pattern, text, *, flags=0):
    return re.fullmatch(pattern, text, flags)


def replace(pattern, replacement, text, *, count=0, flags=0):
    return re.sub(pattern, replacement, text, count=count, flags=flags)


def split(pattern, text, *, maxsplit=0, flags=0):
    return re.split(pattern, text, maxsplit=maxsplit, flags=flags)
