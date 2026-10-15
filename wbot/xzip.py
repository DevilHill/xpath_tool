"""ZIP 归档工具。解压先检查所有路径，拒绝符号链接与目录穿越。"""
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import zipfile


def _member_path(name):
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or normalized.startswith("/") or PureWindowsPath(name).drive:
        raise ValueError(f"不安全的 ZIP 路径：{name!r}")
    for part in parts:
        if part in ("..", ".") or ":" in part or "\x00" in part or part.endswith((".", " ")):
            raise ValueError(f"不安全的 ZIP 路径：{name!r}")
        if part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise ValueError(f"ZIP 路径包含保留设备名：{name!r}")
    return Path(*parts)


def zip(file_folder_path, zip_file_path, *, compress_level=5, password=None, overwrite=False):
    """压缩单一路径或路径列表；目录连同目录名保存。标准库不支持加密写入。"""
    if password is not None:
        raise NotImplementedError("不支持创建加密 ZIP；请省略 password")
    if not isinstance(compress_level, int) or not 0 <= compress_level <= 9:
        raise ValueError("compress_level 必须为 0 至 9 的整数")
    sources = [file_folder_path] if isinstance(file_folder_path, (str, os.PathLike)) else list(file_folder_path)
    if not sources:
        raise ValueError("至少指定一个源文件或目录")
    output = Path(zip_file_path).absolute()
    entries, names = [], set()
    for source in sources:
        source = Path(source).absolute()
        if not source.exists():
            raise FileNotFoundError(str(source))
        candidates = [source, *source.rglob("*")] if source.is_dir() else [source]
        for candidate in candidates:
            if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
                raise ValueError(f"不支持归档符号链接或目录联接：{candidate}")
            if candidate.resolve() == output.resolve():
                raise ValueError("归档文件不能包含自身")
            relative = _member_path(candidate.relative_to(source.parent).as_posix())
            key = relative.as_posix().casefold()
            if key in names:
                raise ValueError(f"归档路径重复：{relative}")
            names.add(key)
            entries.append((candidate, relative.as_posix()))
    with zipfile.ZipFile(output, "w" if overwrite else "x", compression=zipfile.ZIP_DEFLATED, compresslevel=compress_level) as archive:
        for path, name in entries:
            archive.write(path, arcname=name)
    return str(output)


def unzip(zip_file_path, unzip_dir_path, *, password=None, overwrite=False, max_files=10000, max_bytes=1024 * 1024 * 1024):
    """安全解压；默认上限一万个条目、1 GiB 解压大小，返回文件路径列表。"""
    if max_files <= 0 or max_bytes <= 0:
        raise ValueError("max_files 与 max_bytes 必须为正数")
    base = Path(unzip_dir_path).absolute()
    if base.is_symlink() or (hasattr(base, "is_junction") and base.is_junction()):
        raise ValueError("解压根目录不能为符号链接或目录联接")
    root = base.resolve()
    pwd = password.encode("utf-8") if isinstance(password, str) else password
    with zipfile.ZipFile(zip_file_path, "r") as archive:
        members = archive.infolist()
        if len(members) > max_files or sum(info.file_size for info in members) > max_bytes:
            raise ValueError("ZIP 超出允许的解压数量或大小")
        planned, names = [], set()
        for info in members:
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f"不支持 ZIP 中的链接或特殊文件：{info.filename}")
            relative = _member_path(info.filename)
            key = relative.as_posix().casefold()
            if key in names:
                raise ValueError(f"ZIP 中的路径重复：{info.filename}")
            names.add(key)
            target = root / relative
            if not target.resolve().is_relative_to(root):
                raise ValueError(f"ZIP 路径越界：{info.filename}")
            for ancestor in [target, *target.parents]:
                if ancestor == root:
                    break
                if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
                    raise ValueError(f"目标路径包含链接：{ancestor}")
                if ancestor != target and ancestor.exists() and not ancestor.is_dir():
                    raise FileExistsError(str(ancestor))
            if target.exists() and not (info.is_dir() and target.is_dir()):
                if not overwrite or target.is_dir():
                    raise FileExistsError(str(target))
            planned.append((info, target))
        # 提前发现文件 a 与 a/b 的冲突，避免写到一半才报错。
        file_paths = {target for info, target in planned if not info.is_dir()}
        for info, target in planned:
            if any(parent in file_paths for parent in target.parents):
                raise ValueError(f"ZIP 文件与目录冲突：{info.filename}")
        extracted, total = [], 0
        for info, target in planned:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, pwd=pwd) as src, target.open("wb" if overwrite else "xb") as dst:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    total += len(block)
                    if total > max_bytes:
                        raise ValueError("ZIP 实际解压大小超限")
                    dst.write(block)
            extracted.append(str(target))
    return extracted
