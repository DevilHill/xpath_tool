"""企业策略强制安装（Windows 注册表策略 + 自托管 CRX）。

**为什么需要它**：用户希望扩展装进**日常那个浏览器**并且**重启后还在**。实测结论：

  * `--load-extension`：品牌版 Chrome ≥137 直接忽略；即便生效也是会话级、不持久。
  * CDP `Extensions.loadUnpacked`：能装、当场生效，但**重启后就没了**
    （已用 chrome://extensions 列表验证：装完在列表里，重启后消失）。
  * 所以「自动 + 持久 + 装进现有 profile」在 Chrome 上只剩**企业策略**这一条路。

原理：

  1. 生成/复用一把 RSA 密钥 → 扩展 ID 固定（`sha256(SPKI DER)[:16]` 的 a-p 编码）
  2. 把 SPKI 的 base64 写进扩展 manifest 的 ``key`` 字段（与签名密钥一致）
  3. 打包并签名成 ``extension.crx``（见 ``app/crx.py``），生成 ``update.xml``
  4. 写注册表策略::

        HKCU\\Software\\Policies\\<厂商>\\<产品>\\ExtensionInstallForcelist
            "1" = "<扩展ID>;<update_url>"

  5. ``update_url`` 指向 **exe 自带的 HTTP 服务**
     （``http://127.0.0.1:<port>/extension/update.xml``）——
     桌面版本身就是那个「常驻本地更新服务」，不需要额外起进程。

⚠️ **副作用（必须让用户知情）**：

  * Chrome/Edge 会显示「**由贵单位管理**」横幅
  * 扩展由策略接管，用户无法在扩展管理页直接删除（要用本工具的「卸载策略」）
  * 桌面版没运行时 Chrome 拉不到 update.xml；**已装上的版本仍然可用**，
    只是拿不到更新

⚠️ **它不保证成功，也不代表已安装**：``ExtensionInstallForcelist`` 是**受管设备/组织**用的策略。
自托管强制安装对浏览器版本与设备管理状态有前提。普通个人电脑上，写 ``HKCU`` 这一步可能被安全策略、
组策略或安全软件**拒绝**（典型 ``WinError 5 拒绝访问``）；即使写入成功，也**只是配置写入**，
不等于浏览器接受了策略、更不等于扩展已安装 —— 这是三个不同状态。被拒绝时应**如实报错并给出引导安装
退路**，不得绕过安全限制。

本模块只写 ``HKCU``（当前用户），不需要管理员权限。**不碰 HKLM。**
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from . import crx

APP_DIR_NAME = "XPathStudio"

# 各浏览器的策略根路径（HKCU 下）。产品名与厂商路径各不相同。
POLICY_BROWSERS: dict[str, str] = {
    "chrome": r"Software\Policies\Google\Chrome",
    "edge": r"Software\Policies\Microsoft\Edge",
    "brave": r"Software\Policies\BraveSoftware\Brave",
    "chromium": r"Software\Policies\Chromium",
}

FORCELIST_VALUE = "ExtensionInstallForcelist"

# winreg 只在 Windows 上有
try:  # pragma: no cover - 平台分支
    import winreg  # type: ignore
except Exception:  # noqa: BLE001
    winreg = None  # type: ignore


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def policy_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_DIR_NAME / "policy"


def key_file() -> Path:
    return policy_root() / "extension-key.json"


def crx_dir() -> Path:
    """注入了 key、并改好端口的扩展副本（CRX 就是从这里打的）。"""
    return policy_root() / "extension-crx"


def crx_file() -> Path:
    return policy_root() / "extension.crx"


# --------------------------------------------------------------------------- #
# 密钥与扩展副本
# --------------------------------------------------------------------------- #
def ensure_key() -> tuple[dict[str, int], bool]:
    """返回 (key, 是否新建)。密钥存在 ``policy/extension-key.json``。"""
    return crx.load_or_create_key(key_file())


def _read_manifest_version(ext_dir: Path) -> str:
    try:
        mf = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))
        return str(mf.get("version") or "0.0.0")
    except Exception:  # noqa: BLE001
        return "0.0.0"


def materialize_extension(src_dir: str | Path, port: int, key: dict[str, int]) -> Path:
    """把扩展复制到 ``policy/extension-crx``，注入 ``key`` 并改写桥接端口。

    不直接改源码目录：源码运行时会污染 git 工作区。
    """
    src = Path(src_dir)
    dest = crx_dir()
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)

    # 1) 端口改写（复用 extension_installer 的正则逻辑）
    from .extension_installer import _patch_bridge_port
    _patch_bridge_port(dest, port)

    # 2) 注入 manifest 的 key，使未打包加载与 CRX 得到同一个扩展 ID
    mf_path = dest / "manifest.json"
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    mf["key"] = crx.manifest_key(key["n"], key["e"])
    mf_path.write_text(json.dumps(mf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def extension_id() -> str:
    key, _ = ensure_key()
    return crx.extension_id(key["n"], key["e"])


# --------------------------------------------------------------------------- #
# 产物
# --------------------------------------------------------------------------- #
_crx_cache: dict[str, Any] = {"mtime": None, "blob": b""}


def build_crx(src_dir: str | Path, port: int) -> tuple[bytes, str, str]:
    """打包并签名，返回 (crx 字节, 扩展 ID, 版本号)。带 mtime 缓存。"""
    key, _ = ensure_key()
    dest = materialize_extension(src_dir, port, key)
    version = _read_manifest_version(dest)

    try:
        newest = max(p.stat().st_mtime for p in dest.rglob("*") if p.is_file())
    except ValueError:
        newest = 0.0
    cache_key = f"{newest}:{version}:{port}"
    if _crx_cache["mtime"] == cache_key and _crx_cache["blob"]:
        return _crx_cache["blob"], crx.extension_id(key["n"], key["e"]), version

    zip_bytes = crx.zip_extension(dest)
    blob = crx.build_crx3(zip_bytes, key)
    crx_file().parent.mkdir(parents=True, exist_ok=True)
    crx_file().write_bytes(blob)
    _crx_cache["mtime"] = cache_key
    _crx_cache["blob"] = blob
    return blob, crx.extension_id(key["n"], key["e"]), version


def update_xml(port: int, ext_id: str = "", version: str = "") -> str:
    eid = ext_id or extension_id()
    if not version:
        version = _read_manifest_version(crx_dir()) if crx_dir().is_dir() else "0.0.0"
    url = f"http://127.0.0.1:{int(port)}/extension/extension.crx"
    return crx.update_manifest_xml(eid, version, url)


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #
def _policy_path(browser_key: str) -> str | None:
    root = POLICY_BROWSERS.get(browser_key)
    if not root:
        return None
    return root + "\\" + FORCELIST_VALUE


def _registry_error(exc: Exception, stage: str, diagnostics: dict | None) -> None:
    if diagnostics is not None:
        diagnostics.update({"stage": stage, "errorType": type(exc).__name__,
                            "systemError": str(exc), "winerror": getattr(exc, "winerror", None)})


def read_forcelist(browser_key: str, diagnostics: dict | None = None) -> list[str] | None:
    """读取现有的 forcelist 值（按名字排序）。无策略/不支持返回 None。"""
    if winreg is None:
        return None
    path = _policy_path(browser_key)
    if not path:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            out: list[tuple[int, str]] = []
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(k, i)
                except OSError as exc:
                    if getattr(exc, "winerror", None) == 259:  # ERROR_NO_MORE_ITEMS
                        break
                    raise
                i += 1
                out.append((int(name) if str(name).isdigit() else 9999, str(val)))
            out.sort(key=lambda t: t[0])
            return [v for _, v in out]
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        _registry_error(exc, "policy-read", diagnostics)
        return None


def write_forcelist(browser_key: str, entries: list[str], diagnostics: dict | None = None) -> bool:
    """把 forcelist 整体写成 ``entries``（从 "1" 开始编号）。空列表则删除该键。"""
    if winreg is None:
        return False
    path = _policy_path(browser_key)
    if not path:
        return False
    try:
        if not entries:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass
            return True
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        try:
            # 必须先完整枚举；访问拒绝不能被当成「枚举完了」而继续写入。
            stale = []
            i = 0
            while True:
                try:
                    name, _, _ = winreg.EnumValue(key, i)
                except OSError as exc:
                    if getattr(exc, "winerror", None) == 259:
                        break
                    raise
                if str(name).isdigit() and int(name) > len(entries):
                    stale.append(name)
                i += 1
            for idx, val in enumerate(entries, start=1):
                winreg.SetValueEx(key, str(idx), 0, winreg.REG_SZ, val)
            for name in stale:
                winreg.DeleteValue(key, name)
        finally:
            winreg.CloseKey(key)
        return True
    except Exception as exc:  # noqa: BLE001
        _registry_error(exc, "policy-write", diagnostics)
        return False


def status(browser_key: str, ext_id: str = "") -> dict[str, Any]:
    """查询策略状态。"""
    # 状态查询是只读操作，不为查询创建密钥或安装产物。
    eid = ext_id
    if not eid and key_file().exists():
        key = crx.load_key(key_file())
        if not key or "n" not in key or "e" not in key:
            return {"supported": False, "installed": False, "policyConfigured": False,
                    "reason": "本地签名密钥不可读取，无法确认本扩展的策略；未重新生成密钥"}
        eid = crx.extension_id(key["n"], key["e"])
    detail: dict[str, Any] = {}
    entries = read_forcelist(browser_key, detail)
    if entries is None:
        return {"supported": False, "installed": False, "policyConfigured": False,
                "installationVerified": False, "entries": [], "diagnostics": detail,
                "reason": detail.get("systemError") or "非 Windows 或无法读取注册表"}
    mine = [v for v in entries if v.split(";")[0].strip() == eid]
    return {
        "supported": True,
        "installed": bool(mine),  # 旧客户端兼容字段，仅表示策略条目存在
        "policyConfigured": bool(mine),
        "installationVerified": False,
        "entries": entries,
        "mine": mine,
        "extId": eid,
        "policyPath": f"HKCU\\{_policy_path(browser_key) or ''}",
    }


# --------------------------------------------------------------------------- #
# 安装 / 卸载
# --------------------------------------------------------------------------- #
def install_policy(browser_key: str, src_dir: str | Path, port: int) -> dict[str, Any]:
    """写策略强制安装。返回结果字典（``ok`` / ``error`` / ``steps`` 等）。"""
    if winreg is None:
        return {"ok": False, "error": "企业策略安装仅支持 Windows"}
    path = _policy_path(browser_key)
    if not path:
        return {"ok": False, "error": f"未知浏览器：{browser_key}"}

    try:
        blob, eid, version = build_crx(src_dir, port)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"打包签名失败：{type(exc).__name__}: {exc}"}

    url = f"http://127.0.0.1:{int(port)}/extension/update.xml"
    entry = f"{eid};{url}"

    diagnostics: dict[str, Any] = {}
    entries = read_forcelist(browser_key, diagnostics)
    if entries is None:
        return {"ok": False, "stage": "policy-read", "policyPath": f"HKCU\\{path}",
                "diagnostics": diagnostics,
                "error": "读取现有策略失败，为避免覆盖已有策略已中止：" + diagnostics.get("systemError", "未知错误")}
    # 去掉同 ID 的旧条目（可能端口变了），再追加
    entries = [v for v in entries if v.split(";")[0].strip() != eid]
    entries.append(entry)

    if not write_forcelist(browser_key, entries, diagnostics):
        return {"ok": False, "stage": "policy-write", "policyPath": f"HKCU\\{path}",
                "diagnostics": diagnostics, "fallback": "guided",
                "error": "写入注册表失败：" + diagnostics.get("systemError", "未知错误"),
                "warnings": ["操作可能部分完成，不能据此判定扩展已安装。",
                             "如果权限或组织策略禁止安装，请联系管理员；不要关闭防护或绕过限制。"]}

    return {
        "ok": True,
        "method": "policy",
        "extId": eid,
        "version": version,
        "crxSize": len(blob),
        "crxPath": str(crx_file()),
        "policyPath": f"HKCU\\{path}",
        "value": entry,
        "updateUrl": url,
        "entries": entries,
        "steps": [
            "已写入当前用户策略配置；尚未验证浏览器接受策略或扩展安装成功",
            "保存工作后完全退出并重新打开浏览器，在扩展管理页检查实际状态",
            "仅在浏览器允许自托管安装时，才会从运行中的桌面版拉取 update.xml 与 extension.crx",
            "扩展管理页会显示「由贵单位管理」，这是策略安装的正常现象",
            "以后想卸载：点「卸载策略」并重启浏览器",
        ],
        "warnings": [
            "自托管扩展强制安装受浏览器及设备管理条件限制；写入HKCU不等于满足企业管理条件。",
            "浏览器会显示「由贵单位管理」横幅",
            "扩展由策略接管，无法在扩展管理页直接删除",
            "桌面版未运行时浏览器拉不到更新；已安装的版本仍可正常使用",
        ],
    }


def remove_policy(browser_key: str) -> dict[str, Any]:
    """只删掉**本扩展**的策略条目，保留用户其他策略。"""
    if winreg is None:
        return {"ok": False, "error": "企业策略安装仅支持 Windows"}
    path = _policy_path(browser_key)
    if not path:
        return {"ok": False, "error": f"未知浏览器：{browser_key}"}

    eid = extension_id()
    entries = read_forcelist(browser_key)
    if entries is None:
        return {"ok": False, "error": "读取现有策略失败"}
    mine = [v for v in entries if v.split(";")[0].strip() == eid]
    if not mine:
        return {"ok": True, "removed": 0, "note": "策略里没有本扩展，无需卸载"}

    rest = [v for v in entries if v.split(";")[0].strip() != eid]
    diagnostics: dict[str, Any] = {}
    if not write_forcelist(browser_key, rest, diagnostics):
        return {"ok": False, "stage": "policy-remove", "policyPath": f"HKCU\\{path}",
                "diagnostics": diagnostics,
                "error": "移除策略失败：" + diagnostics.get("systemError", "未知错误")}
    return {
        "ok": True,
        "removed": len(mine),
        "remaining": rest,
        "policyPath": f"HKCU\\{path}",
        "steps": [
            "已移除本扩展的强制安装策略",
            "完全退出并重新打开浏览器",
            "浏览器会随之卸载该扩展（可能需要几秒到一次重启）",
        ],
    }


def cleanup_artifacts() -> None:
    """删除生成的密钥与 CRX（谨慎使用：删了密钥扩展 ID 会变）。"""
    shutil.rmtree(policy_root(), ignore_errors=True)
    _crx_cache["mtime"] = None
    _crx_cache["blob"] = b""
