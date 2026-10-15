"""CSV 表格读写，支持列表行和字典行。"""
import csv as _csv
from pathlib import Path


def read(path, *, header=True, encoding="utf-8-sig", delimiter=","):
    with Path(path).open("r", encoding=encoding, newline="") as stream:
        reader = _csv.DictReader(stream, delimiter=delimiter) if header else _csv.reader(stream, delimiter=delimiter)
        return list(reader)


def write(path, rows, *, fieldnames=None, header=True, encoding="utf-8-sig", delimiter=",", overwrite=False):
    rows = list(rows)
    dictionaries = bool(rows and isinstance(rows[0], dict)) or fieldnames is not None
    fields = list(fieldnames) if fieldnames is not None else (list(rows[0]) if dictionaries else None)
    with Path(path).open("w" if overwrite else "x", encoding=encoding, newline="") as stream:
        if dictionaries:
            writer = _csv.DictWriter(stream, fieldnames=fields, delimiter=delimiter)
            if header:
                writer.writeheader()
        else:
            writer = _csv.writer(stream, delimiter=delimiter)
        writer.writerows(rows)
    return str(path)
