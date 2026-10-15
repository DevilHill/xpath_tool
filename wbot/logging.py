"""脚本日志；使用Python标准日志，不改写调用者的全局配置。"""
import logging as _logging

_logger = _logging.getLogger("wbot")
_logger.addHandler(_logging.NullHandler())


def configure(level="INFO", filename=None):
    """显式启用wbot控制台或UTF-8文件日志。"""
    handler = _logging.FileHandler(filename, encoding="utf-8") if filename else _logging.StreamHandler()
    handler.setFormatter(_logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    for old in list(_logger.handlers):
        _logger.removeHandler(old)
        old.close()
    _logger.addHandler(handler)
    _logger.setLevel(level)
    _logger.propagate = False
    return _logger


debug = _logger.debug
info = _logger.info
warning = _logger.warning
warn = warning
error = _logger.error
exception = _logger.exception
