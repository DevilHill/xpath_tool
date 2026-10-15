"""JSON 序列化及文件存储，不使用 eval。"""
import json as _json
from . import files

JSONDecodeError = _json.JSONDecodeError
loads = _json.loads


def dumps(value, *, indent=2, ensure_ascii=False, **kwargs):
    return _json.dumps(value, indent=indent, ensure_ascii=ensure_ascii, **kwargs)


def load(path, *, encoding="utf-8-sig"):
    return loads(files.read_text(path, encoding=encoding))


def dump(value, path, *, overwrite=False, encoding="utf-8", indent=2):
    return files.write_text(path, dumps(value, indent=indent), encoding=encoding, overwrite=overwrite)


parse = loads
stringify = dumps
