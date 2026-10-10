"""诊断：
1) 未打包扩展的 ID 推导公式（sha256(path) -> 前 32 位十六进制 -> 映射到 a-p）
2) 真实 profile 的 Preferences 里扩展条目长什么样（尤其是 location==4 的「已解压」）
   —— 这是要照着写的模板
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")

HEX = "0123456789abcdef"
AP = "abcdefghijklmnop"


def unpacked_id(path: str) -> str:
    """Chrome 对未打包扩展的 ID：sha256(路径) 的前 32 个 hex 字符，逐位映射 0-9a-f -> a-p。"""
    h = hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]
    return "".join(AP[HEX.index(c)] for c in h)


def main() -> int:
    print("=" * 72)
    print("1) 未打包扩展 ID 公式校验")
    print("=" * 72)
    print(f"  扩展目录: {EXT}")
    print(f"  推导 ID : {unpacked_id(EXT)}")
    print("  实测 ID : kobcjdhedhdfjcmdlmflhhiikccedhke（上一步 CDP Extensions.loadUnpacked 返回）")
    print(f"  {'✅ 公式正确' if unpacked_id(EXT) == 'kobcjdhedhdfjcmdlmflhhiikccedhke' else '❌ 公式不符，需修正'}")

    print()
    print("=" * 72)
    print("2) 真实 profile 的扩展条目（找 location==4 的模板）")
    print("=" * 72)
    profiles = {
        "chrome": os.path.join(os.environ.get("LOCALAPPDATA", ""),
                               "Google", "Chrome", "User Data", "Default", "Preferences"),
        "edge": os.path.join(os.environ.get("LOCALAPPDATA", ""),
                             "Microsoft", "Edge", "User Data", "Default", "Preferences"),
    }
    for name, p in profiles.items():
        print(f"\n--- {name}: {p}")
        if not os.path.exists(p):
            print("    （文件不存在）")
            continue
        try:
            with open(p, encoding="utf-8") as f:
                prefs = json.load(f)
        except Exception as exc:  # noqa: BLE001
            print(f"    读取失败：{exc}")
            continue
        entries = ((prefs.get("extensions") or {}).get("settings") or {})
        print(f"    扩展条目总数：{len(entries)}")
        by_loc: dict = {}
        sample4 = None
        for k, v in entries.items():
            loc = (v or {}).get("location")
            by_loc[loc] = by_loc.get(loc, 0) + 1
            if loc == 4 and sample4 is None:
                sample4 = (k, v)
        print(f"    location 分布：{by_loc}")
        if sample4:
            k, v = sample4
            print(f"    location==4 样例 id={k}")
            keep = {kk: v.get(kk) for kk in
                    ("location", "path", "state", "from_webstore", "creation_flags",
                     "was_installed_by_default", "was_installed_by_oem", "install_time",
                     "manifest")}
            print("    字段：")
            print("      " + json.dumps(keep, ensure_ascii=False, indent=6).replace("\n", "\n      "))
        else:
            print("    ⚠️ 没有 location==4（已解压）的样例")
        # 该 profile 顶层 extensions 下还有哪些键
        print(f"    extensions 顶层键：{sorted((prefs.get('extensions') or {}).keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
