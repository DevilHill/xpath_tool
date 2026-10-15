"""目录创建、枚举、复制与删除，递归删除须显式开启。"""
from pathlib import Path
import shutil
from .files import safe_path


def exists(path):
    return Path(path).is_dir()


def create(path, *, parents=True, exist_ok=True):
    target = Path(path)
    target.mkdir(parents=parents, exist_ok=exist_ok)
    return str(target)


def list_folders(path, *, recursive=False):
    base = Path(path)
    if not base.is_dir():
        raise NotADirectoryError(str(base))
    return sorted(str(p) for p in (base.rglob("*") if recursive else base.iterdir()) if p.is_dir())


def copy(source, destination, *, overwrite=False):
    source, target = Path(source).resolve(), Path(destination).resolve()
    if source == target or target.is_relative_to(source):
        raise ValueError("目标目录不能位于源目录内")
    # 保留符号链接本身，不跟随链接读取目录外的数据。
    shutil.copytree(source, target, dirs_exist_ok=overwrite, symlinks=True)
    return str(target)


def delete(path, *, recursive=False, missing_ok=False):
    target = Path(path).absolute()
    if target.is_symlink():
        raise ValueError("目录删除不接受符号链接")
    resolved = target.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve() or resolved == Path.cwd().resolve():
        raise ValueError("拒绝删除根目录、用户目录或当前工作目录")
    if not target.exists():
        if missing_ok:
            return
        raise FileNotFoundError(str(target))
    if recursive:
        shutil.rmtree(target)
    else:
        target.rmdir()
