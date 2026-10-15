"""命名元素选择器，使用 wbot 自有元素库。"""
from __future__ import annotations

from .elements import ElementLibrary, validate_xpath


class Selector:
    def __init__(self, value, meta=None):
        record = dict(value) if isinstance(value, dict) else dict(meta or {}, xpath=value)
        self._record = record
        self._record['xpath'] = validate_xpath(record.get('xpath'))

    def xpath(self):
        return self._record['xpath']

    @property
    def name(self):
        return self._record.get('name', '')

    @property
    def group(self):
        return self._record.get('group', '默认')

    @property
    def frame(self):
        return self.to_dict().get('frame')

    @property
    def url(self):
        return self._record.get('url', '')

    def to_dict(self):
        from copy import deepcopy
        return deepcopy(self._record)

    def __str__(self):
        return self.xpath()


class SelectorStore:
    """path 为 SQLite 文件路径；省略时与 XPath Studio 共享默认元素库。"""
    def __init__(self, path=None):
        self.library = ElementLibrary(path)

    def get(self, name, group='默认'):
        return Selector(self.library.get_by_name(name, group))

    def __call__(self, name, group='默认'):
        return self.get(name, group)
