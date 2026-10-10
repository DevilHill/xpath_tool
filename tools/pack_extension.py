"""把浏览器扩展打包成 zip，便于分发 / 备份。

用法：python tools/pack_extension.py
产物：dist/xpath-studio-extension.zip
"""
from __future__ import annotations

import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")
OUT_DIR = os.path.join(ROOT, "dist")
OUT = os.path.join(OUT_DIR, "xpath-studio-extension.zip")

SKIP_DIRS = {"__pycache__", ".git"}


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, dirs, files in os.walk(EXT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in sorted(files):
                if name.endswith((".pyc", ".map")):
                    continue
                full = os.path.join(base, name)
                rel = os.path.relpath(full, EXT)
                z.write(full, rel)
                count += 1
    size = os.path.getsize(OUT)
    print(f"已打包 {count} 个文件 -> {OUT}（{size / 1024:.1f} KB）")
    print("安装：chrome://extensions/ -> 开发者模式 -> 加载已解压的扩展程序")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
