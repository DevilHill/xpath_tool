"""一键打包为 Windows exe。

用法（在项目根目录）：
    python build.py            # 打包（窗口模式，无控制台）
    python build.py --console  # 带控制台，便于排查问题

产物：dist/XPathStudio.exe
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(ROOT, "app", "web", "app.ico")
EXT_DIR = os.path.join(ROOT, "extension")


def main() -> int:
    console = "--console" in sys.argv
    sep = ";" if os.name == "nt" else ":"

    if not os.path.isdir(EXT_DIR):
        print("[警告] 未找到 extension/ 目录，打包后将无法一键安装浏览器扩展。")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "XPathStudio",
        "--add-data", f"app/web{sep}web",
        # 浏览器扩展随 exe 一起分发，供「一键安装」释放到稳定目录
        "--add-data", f"extension{sep}extension",
        # 企业策略安装相关的模块是在函数体内按需 import 的（避免非 Windows 下
        # 提前触碰 winreg），显式声明防止 PyInstaller 漏收：
        #   app/crx.py            —— 纯标准库 CRX3 签名 / 打包
        #   app/policy_install.py —— ExtensionInstallForcelist 策略读写
        "--hidden-import", "app.crx",
        "--hidden-import", "app.policy_install",
        # pywebview / pythonnet 需要显式声明
        "--hidden-import", "webview",
        "--hidden-import", "webview.platforms.edgechromium",
        "--hidden-import", "clr",
        "--collect-all", "webview",
    ]
    if not console:
        cmd.append("--windowed")
    if os.path.exists(ICON):
        cmd += ["--icon", ICON]
    cmd.append(os.path.join(ROOT, "run.py"))

    print("执行打包命令：\n ", " ".join(cmd), "\n")
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc != 0:
        print("\n[失败] PyInstaller 返回码", rc)
        return rc

    exe = os.path.join(ROOT, "dist", "XPathStudio.exe")
    print("\n[完成] 产物：", exe if os.path.exists(exe) else "(未找到，请检查输出)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
