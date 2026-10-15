"""文件读写工具。写入默认拒绝覆盖，路径可选限制在指定根目录内。"""
from pathlib import Path
import hashlib
import shutil


def safe_path(path, *, root=None):
    candidate = Path(path).expanduser()
    if root is not None:
        base = Path(root).expanduser().resolve()
        candidate = candidate if candidate.is_absolute() else base / candidate
        candidate = candidate.resolve()
        if not candidate.is_relative_to(base):
            raise ValueError("路径超出允许的根目录")
    return candidate


def exists(path):
    return Path(path).is_file()


def read_text(path, *, encoding="utf-8-sig"):
    return Path(path).read_text(encoding=encoding)


def read_bytes(path):
    return Path(path).read_bytes()


def write_text(path, content, *, encoding="utf-8", overwrite=False, create_parents=False):
    if not isinstance(content, str):
        raise TypeError("content 必须为字符串")
    target = Path(path)
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w" if overwrite else "x", encoding=encoding, newline="") as stream:
        stream.write(content)
    return str(target)


def write_bytes(path, content, *, overwrite=False, create_parents=False):
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise TypeError("content 必须为 bytes 类型")
    target = Path(path)
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb" if overwrite else "xb") as stream:
        stream.write(content)
    return str(target)


def append_text(path, content, *, encoding="utf-8"):
    with Path(path).open("a", encoding=encoding, newline="") as stream:
        stream.write(content)
    return str(path)


def copy(source, destination, *, overwrite=False):
    source, target = Path(source), Path(destination)
    if source.resolve() == target.resolve():
        raise ValueError("源文件与目标文件不能相同")
    # 独占创建避免默认情况下覆盖已有内容。
    with source.open("rb") as src, target.open("wb" if overwrite else "xb") as dst:
        shutil.copyfileobj(src, dst)
    return str(target)


def move(source, destination, *, overwrite=False):
    result = copy(source, destination, overwrite=overwrite)
    Path(source).unlink()
    return result


def delete(path, *, missing_ok=False):
    target = Path(path)
    if target.is_dir():
        raise IsADirectoryError(str(target))
    target.unlink(missing_ok=missing_ok)


def size(path):
    return Path(path).stat().st_size


def checksum(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def list_files(directory, pattern="*", *, recursive=False):
    base = Path(directory)
    if not base.is_dir():
        raise NotADirectoryError(str(base))
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ValueError("pattern 必须位于 directory 内")
    return sorted(str(p) for p in (base.rglob(pattern) if recursive else base.glob(pattern)) if p.is_file())


read = read_text
write = write_text
