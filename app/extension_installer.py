"""浏览器扩展安装入口（Chromium 系 / Windows）。

auto/guided：默认优先 Chrome，打开现有浏览器的扩展页并复制目录，用户手动加载。
flag/cdp：必须显式选择，在专用 profile 中临时加载，不安装到日常浏览器。
policy：受管理环境限制的企业策略，不把策略写入视为扩展已安装。

本地扩展没有应用商店发布 ID，不能套用已上架扩展的外部安装流程。
连接计数是全局状态，不能证明所选浏览器/个人资料已完成安装。
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import ws_bridge

APP_DIR_NAME = "XPathStudio"

# --------------------------------------------------------------------------- #
# 浏览器探测表
# --------------------------------------------------------------------------- #
_BROWSERS: list[dict[str, Any]] = [
    {
        "key": "chrome",
        "name": "Google Chrome",
        "branded": True,   # 品牌版：137+ 忽略 --load-extension
        "paths": [
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        ],
        "app_paths": [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"],
    },
    {
        "key": "edge",
        "name": "Microsoft Edge",
        "branded": False,
        "paths": [
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
        ],
        "app_paths": [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"],
    },
    {
        "key": "brave",
        "name": "Brave",
        "branded": False,
        "paths": [
            r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "app_paths": [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"],
    },
    {
        "key": "chromium",
        "name": "Chromium",
        "branded": False,
        "paths": [
            r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
            r"%ProgramFiles%\Chromium\Application\chrome.exe",
        ],
        "app_paths": [],
    },
]

# Chrome 从哪个大版本开始忽略 --load-extension
CHROME_FLAG_REMOVED_AT = 137
# CDP browser.addExtension 从哪个大版本开始可用
CDP_MIN_VERSION = 126


def _expand(p: str) -> str:
    return os.path.expandvars(p)


def _read_app_path(rel: str) -> str:
    """从注册表 App Paths 读取可执行文件路径（HKCU + HKLM，32/64 位视图）。"""
    try:
        import winreg  # type: ignore
    except Exception:  # noqa: BLE001
        return ""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, rel, 0, winreg.KEY_READ | view) as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val and os.path.exists(val):
                        return val
            except Exception:  # noqa: BLE001
                continue
    return ""


def _pe_file_version(path: str) -> str:
    """从 PE 资源里读文件版本（Windows 专用，纯 ctypes）。

    **为什么不能用 `exe --version`**：Windows 上的 Chrome/Edge 是 GUI 子系统程序，
    `chrome.exe --version` 并不会打印版本号 —— 实测它输出的是 GBK 编码的
    「正在现有的浏览器会话中打开。」并且**真的会去开一个标签页**，
    Edge 更是直接返回空。所以必须从文件本身的版本资源里读。
    """
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.WinDLL("version")
        size = ver.GetFileVersionInfoSizeW(ctypes.c_wchar_p(path), None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(ctypes.c_wchar_p(path), 0, size, buf):
            return ""

        # 1) 先试固定版本块，拿到数字版本号（最稳，不依赖语言）
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if ver.VerQueryValueW(buf, ctypes.c_wchar_p("\\"), ctypes.byref(ptr), ctypes.byref(length)) and length.value:
            class VS_FIXEDFILEINFO(ctypes.Structure):
                _fields_ = [
                    ("dwSignature", wintypes.DWORD),
                    ("dwStrucVersion", wintypes.DWORD),
                    ("dwFileVersionMS", wintypes.DWORD),
                    ("dwFileVersionLS", wintypes.DWORD),
                    ("dwProductVersionMS", wintypes.DWORD),
                    ("dwProductVersionLS", wintypes.DWORD),
                    ("dwFileFlagsMask", wintypes.DWORD),
                    ("dwFileFlags", wintypes.DWORD),
                    ("dwFileOS", wintypes.DWORD),
                    ("dwFileType", wintypes.DWORD),
                    ("dwFileSubtype", wintypes.DWORD),
                    ("dwFileDateMS", wintypes.DWORD),
                    ("dwFileDateLS", wintypes.DWORD),
                ]

            info = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
            ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
            if ms or ls:
                return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"

        # 2) 退而求其次：查 ProductVersion 字符串（形如 "151.0.7922.76"）
        for lang in ("040904B0", "040904E4", "04090000", "000004B0"):
            sub = f"\\StringFileInfo\\{lang}\\ProductVersion"
            if ver.VerQueryValueW(buf, ctypes.c_wchar_p(sub), ctypes.byref(ptr), ctypes.byref(length)) and length.value:
                return ctypes.wstring_at(ptr, length.value).strip("\x00").strip()
        return ""
    except Exception:  # noqa: BLE001
        return ""


def _registry_version(key: str) -> str:
    """Chrome/Edge/Brave 都会在 BLBeacon 里写版本号，作为兜底。"""
    try:
        import winreg  # type: ignore
    except Exception:  # noqa: BLE001
        return ""
    rel = {
        "chrome": r"SOFTWARE\Google\Chrome\BLBeacon",
        "edge": r"SOFTWARE\Microsoft\Edge\BLBeacon",
        "brave": r"SOFTWARE\BraveSoftware\Brave-Browser\BLBeacon",
    }.get(key)
    if not rel:
        return ""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, rel, 0, winreg.KEY_READ | view) as k:
                    val, _ = winreg.QueryValueEx(k, "version")
                    if val:
                        return str(val).strip()
            except Exception:  # noqa: BLE001
                continue
    return ""


def browser_version(exe: str, key: str = "") -> str:
    """取浏览器版本号。

    Windows 上只用「读文件版本 / 读注册表」，**绝不调用 `--version`**（见
    ``_pe_file_version`` 的说明：那会真的开一个标签页且拿不到版本）。
    其他平台 `--version` 是可靠的。
    """
    if platform.system() == "Windows":
        v = _pe_file_version(exe)
        if v:
            return v
        return _registry_version(key) if key else ""
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, timeout=8,
            encoding="utf-8", errors="replace",
        )
        return (out.stdout or out.stderr or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _major(version_text: str) -> int:
    for tok in (version_text or "").replace("/", " ").split():
        if tok and tok[0].isdigit() and "." in tok:
            try:
                return int(tok.split(".")[0])
            except Exception:  # noqa: BLE001
                continue
    return 0


def find_browsers() -> list[dict[str, Any]]:
    """返回本机已安装的 Chromium 系浏览器。"""
    found: list[dict[str, Any]] = []
    for spec in _BROWSERS:
        exe = ""
        for p in spec["paths"]:
            cand = _expand(p)
            if os.path.exists(cand):
                exe = cand
                break
        if not exe:
            for rel in spec["app_paths"]:
                exe = _read_app_path(rel)
                if exe:
                    break
        if not exe:
            continue

        ver_text = browser_version(exe, spec["key"])
        major = _major(ver_text)
        # 版本未知时保守处理：品牌版 Chrome 一律不信 --load-extension（137+ 已死）
        if major:
            flag_ok = not (spec["branded"] and major >= CHROME_FLAG_REMOVED_AT)
            cdp_ok = major >= CDP_MIN_VERSION
        else:
            flag_ok = not spec["branded"]
            cdp_ok = True

        if not major:
            note = "无法读取版本号，已按保守策略选择安装方式"
        elif not flag_ok:
            note = "当前 Chrome 需在扩展页手动加载；自动加载仅适用于高级选项中的独立实例"
        elif not cdp_ok:
            note = f"版本较旧（<{CDP_MIN_VERSION}），CDP 安装不可用，将使用 --load-extension"
        else:
            note = ""

        found.append({
            "key": spec["key"],
            "name": spec["name"],
            "path": exe,
            "version": ver_text or "(未知版本)",
            "major": major,
            "branded": spec["branded"],
            "cdp": cdp_ok,
            "flag": flag_ok,
            "recommend": "guided",
            "note": note,
        })
    return found


def pick_browser(browsers: list[dict[str, Any]], key: str = "") -> dict[str, Any] | None:
    if not browsers:
        return None
    if key:
        for b in browsers:
            if b["key"] == key:
                return b
    # 默认优先用户日常使用的 Chrome；具体配置文件由用户在浏览器中确认。
    for pref in ("chrome", "edge", "brave", "chromium"):
        for b in browsers:
            if b["key"] == pref:
                return b
    return browsers[0]


# --------------------------------------------------------------------------- #
# 扩展目录（打包后释放到稳定路径）
# --------------------------------------------------------------------------- #
def _bundle_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        d = base / "extension"
    else:
        d = Path(__file__).resolve().parent.parent / "extension"
    return d if d.is_dir() else None


def _sync_tree(src: Path, dest: Path) -> None:
    """按内容同步，不能仅比较大小；相同长度的版本号/权限改动也必须更新。"""
    for base, _dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        target_dir = dest if rel == "." else dest / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            if name.endswith((".pyc", ".map")):
                continue
            s = Path(base) / name
            d = target_dir / name
            if not d.exists() or d.read_bytes() != s.read_bytes():
                try:
                    shutil.copy2(s, d)
                except OSError as exc:
                    raise OSError(f"无法更新扩展文件 {d}：{exc}") from exc


def _patch_bridge_port(ext_dir: Path, port: int) -> None:
    """把扩展默认桥接地址改成桌面版真实端口。

    新解压的扩展配置里没有用户设置，默认值是 8790；如果桌面版端口顺延了，
    不改这里扩展就连不上。只改释放出来的副本，不动源码目录。
    """
    bg = ext_dir / "background.js"
    import re as _re
    text = bg.read_text(encoding="utf-8")
    new, count = _re.subn(
        r'var DEFAULT_BRIDGE = "http://127\.0\.0\.1:\d+";',
        f'var DEFAULT_BRIDGE = "http://127.0.0.1:{int(port)}";',
        text, count=1,
    )
    if count != 1:
        raise ValueError("扩展桥接地址格式不兼容，无法配置当前桌面版端口")
    if new != text:
        bg.write_text(new, encoding="utf-8")


def stable_extension_dir(port: int) -> Path:
    """返回可交给浏览器的**稳定**扩展目录。

    打包运行时 ``_MEIPASS`` 是临时目录（每次启动都变），不能直接给浏览器用，
    所以先释放到 ``%LOCALAPPDATA%/XPathStudio/extension``。
    """
    src = _bundle_dir()
    if src is None:
        raise FileNotFoundError("找不到扩展目录（extension/），请确认打包时带了 --add-data extension;extension")

    if not getattr(sys, "frozen", False):
        return src  # 源码运行：直接用项目目录，不污染

    dest = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_DIR_NAME / "extension"
    _sync_tree(src, dest)
    _patch_bridge_port(dest, port)
    return dest


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _profile_dir(key: str, suffix: str = "") -> Path:
    d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_DIR_NAME / "browser-profile" / (key + suffix)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _spawn(exe: str, args: list[str]) -> None:
    """启动浏览器（保持可见，用户需要看到它）。"""
    subprocess.Popen([exe, *args], close_fds=True)


def clipboard_set(text: str) -> bool:
    """写系统剪贴板（Win32 API，正确处理中文路径）。"""
    if platform.system() != "Windows":
        return False
    try:
        import ctypes

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        from ctypes import wintypes
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # 默认 ctypes 返回 int，64 位 HGLOBAL/指针会截断，甚至导致进程崩溃。
        u32.OpenClipboard.argtypes = [wintypes.HWND]
        u32.OpenClipboard.restype = wintypes.BOOL
        u32.EmptyClipboard.restype = wintypes.BOOL
        u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        u32.SetClipboardData.restype = wintypes.HANDLE
        k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k32.GlobalAlloc.restype = wintypes.HANDLE
        k32.GlobalLock.argtypes = [wintypes.HANDLE]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        k32.GlobalFree.argtypes = [wintypes.HANDLE]
        k32.GlobalFree.restype = wintypes.HANDLE

        if not u32.OpenClipboard(None):
            return False
        try:
            if not u32.EmptyClipboard():
                return False
            data = text.encode("utf-16-le") + b"\x00\x00"
            h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return False
            p = k32.GlobalLock(h)
            if not p:
                k32.GlobalFree(h)
                return False
            try:
                ctypes.memmove(p, data, len(data))
            finally:
                k32.GlobalUnlock(h)
            if not u32.SetClipboardData(CF_UNICODETEXT, h):
                k32.GlobalFree(h)
                return False
            return True
        finally:
            u32.CloseClipboard()
    except Exception:  # noqa: BLE001
        return False


def wait_for_extension(timeout: float = 30.0, interval: float = 0.5) -> bool:
    """等扩展通过 WebSocket 连回桌面版 —— 这才是「安装成功」的真实证据。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ws_bridge.HUB.stats().get("extensions", 0) > 0:
            return True
        time.sleep(interval)
    return False


def _wait_debugger(port: int, timeout: float = 25.0) -> str:
    """等 DevTools 调试端口就绪，返回 browser 级别的 webSocketDebuggerUrl。"""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                import json as _json
                data = _json.loads(r.read().decode("utf-8"))
                ws = data.get("webSocketDebuggerUrl") or ""
                if ws:
                    return ws
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return ""


# --------------------------------------------------------------------------- #
# 三种安装策略
# --------------------------------------------------------------------------- #
def _try_cdp_method(ws_url: str, method: str, ext_dir: Path, timeout: float = 8.0):
    """用一条**新建**的 CDP 连接尝试一个方法名。

    每个方法单独建连：万一上一个方法把连接读超时了，socket 状态可能已经不干净，
    复用会得到误导性的失败。
    """
    conn = ws_bridge.WSClientConn(ws_url, timeout=timeout)
    try:
        conn.connect()
    except Exception as exc:  # noqa: BLE001
        return False, f"{method}: 连接调试端口失败（{exc}）"
    try:
        resp = conn.call(method, {"path": str(ext_dir)}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return False, f"{method}: {type(exc).__name__}: {exc}"
    finally:
        conn.close()

    if resp is None:
        return False, f"{method}: 无响应（浏览器可能不支持该命令）"
    if not resp.get("error"):
        return True, method
    err = resp["error"]
    msg = err.get("message", err) if isinstance(err, dict) else err
    return False, f"{method}: {msg}"


def _install_via_cdp(browser: dict[str, Any], ext_dir: Path) -> dict[str, Any]:
    profile = _profile_dir(browser["key"])
    debug_port = _free_port()
    _spawn(browser["path"], [
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={profile}",
        # CDP 的 Extensions 域要求显式放开扩展调试（Chrome 132+）
        "--enable-unsafe-extension-debugging",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ])

    ws_url = _wait_debugger(debug_port)
    if not ws_url:
        return {"ok": False, "error": "浏览器调试端口未就绪，无法通过 CDP 安装", "profile": str(profile)}

    # 不同 Chrome 版本叫法不同，两个都试
    errors: list[str] = []
    for method in ("Extensions.loadUnpacked", "browser.addExtension"):
        ok, detail = _try_cdp_method(ws_url, method, ext_dir)
        if ok:
            return {"ok": True, "method": method, "profile": str(profile)}
        errors.append(detail)
    return {"ok": False, "error": "；".join(errors) or "CDP 未返回有效结果", "profile": str(profile)}


def _install_via_flag(browser: dict[str, Any], ext_dir: Path) -> dict[str, Any]:
    if not browser.get("flag", True):
        return {
            "ok": False,
            "error": f"{browser['name']} {browser.get('version','')} 已禁用 --load-extension（Chrome 137 起），请改用 CDP 或引导安装",
        }
    profile = _profile_dir(browser["key"], "-flag")
    _spawn(browser["path"], [
        f"--load-extension={ext_dir}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ])
    return {"ok": True, "profile": str(profile)}


def _install_guided(browser: dict[str, Any], ext_dir: Path) -> dict[str, Any]:
    copied = clipboard_set(str(ext_dir))
    page = "edge://extensions/" if browser["key"] == "edge" else "chrome://extensions/"
    error = ""
    try:
        _spawn(browser["path"], [page])
    except Exception as exc:  # noqa: BLE001
        error = f"无法打开扩展管理页：{type(exc).__name__}: {exc}"
    return {
        "ok": not bool(error),
        "stage": "guided-open",
        "error": error,
        "guided": True,
        "installationVerified": False,
        "copied": copied,
        "path": str(ext_dir),
        "managementUrl": page,
        "steps": [
            ("请手动打开 " if error else "已请求浏览器打开 ") + page,
            "确认扩展页位于你日常使用的浏览器窗口和个人资料中；多个人资料请切到目标窗口后再打开该地址",
            "打开右上角「开发者模式」",
            "点「加载已解压的扩展程序」",
            ("粘贴（Ctrl+V）" if copied else "复制界面中显示的路径，选择") + f"这个目录：{ext_dir}",
            "确认扩展已启用，打开或刷新要抓取的网页，再回到桌面版点击「重新检测连接」",
        ],
    }


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def install(strategy: str = "auto", browser_key: str = "", port: int = 8790,
            verify_timeout: float = 30.0) -> dict[str, Any]:
    if platform.system() != "Windows":
        return {"ok": False, "error": "一键安装目前仅支持 Windows；请手动加载 extension/ 目录"}

    browsers = find_browsers()
    if not browsers:
        return {"ok": False, "error": "没有检测到 Chromium 系浏览器（Chrome / Edge / Brave / Chromium）"}

    if browser_key and not any(b["key"] == browser_key for b in browsers):
        return {"ok": False, "stage": "browser-detect", "error": "所选浏览器未检测到，请重新选择，不会改装到其它浏览器"}
    if strategy not in ("", "auto", "flag", "cdp", "guided", "policy"):
        return {"ok": False, "stage": "strategy", "error": f"不支持的安装方式：{strategy}"}
    browser = pick_browser(browsers, browser_key)
    assert browser is not None

    try:
        ext_dir = stable_extension_dir(port)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stage": "extension-extract", "error": str(exc),
                "browser": browser["name"], "strategy": strategy}

    strat = strategy or "auto"
    if strat == "auto":
        # 默认只引导安装到现有浏览器，独立实例必须显式选择。
        strat = "guided"

    if strat == "cdp" and not browser["cdp"]:
        strat = "flag" if browser["flag"] else "guided"
    if strat == "flag" and not browser["flag"]:
        strat = "cdp" if browser["cdp"] else "guided"

    try:
        if strat == "policy":
            # 企业策略：写注册表 + 自托管 CRX。装进**现有 profile**、重启后仍在。
            # 需要用户重启浏览器才生效，所以不走「等扩展连回来」那套验证。
            from . import policy_install as _policy
            res = _policy.install_policy(browser["key"], ext_dir, port)
        elif strat == "cdp":
            res = _install_via_cdp(browser, ext_dir)
        elif strat == "flag":
            res = _install_via_flag(browser, ext_dir)
        else:
            res = _install_guided(browser, ext_dir)
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    res.update({
        "strategy": strat,
        "browser": browser["name"],
        "browserKey": browser["key"],
        "version": browser["version"],
        "extDir": str(ext_dir),
        "target": "isolated" if strat in ("flag", "cdp") else "existing",
    })

    res.setdefault("stage", "policy-write" if strat == "policy" else "browser-load")
    if strat == "policy":
        # 写入配置不代表浏览器接受了策略，更不代表扩展已安装或已连接。
        res["needsRestart"] = bool(res.get("ok"))
        res["policyConfigured"] = bool(res.get("ok"))
        res["installationVerified"] = False
        if not res.get("ok"):
            res["fallback"] = "guided"
        return res

    if res.get("ok") and not res.get("guided"):
        # 关键：不信任命令返回值，等扩展自己连回来
        res["connected"] = wait_for_extension(verify_timeout)
        if not res["connected"]:
            res["warning"] = (
                "浏览器已启动，但扩展尚未连回桌面版。可能是首次启动较慢，"
                "或浏览器策略拦截；可稍等片刻，或改用「引导安装」。"
            )
            res["fallback"] = "guided"
    elif not res.get("ok"):
        # 自动策略失败时，不要偷偷再开一个窗口；把兜底方案交给用户点一下
        res["fallback"] = "guided"
    return res


# --------------------------------------------------------------------------- #
# 企业策略（转发给 policy_install，顺便做浏览器 key 解析）
# --------------------------------------------------------------------------- #
def _resolve_key(browser_key: str) -> str:
    browsers = find_browsers()
    browser = pick_browser(browsers, browser_key) if browsers else None
    if browser:
        return browser["key"]
    return browser_key or "chrome"


def policy_status(browser_key: str = "") -> dict[str, Any]:
    from . import policy_install as _policy
    key = _resolve_key(browser_key)
    res = _policy.status(key)
    res["browserKey"] = key
    return res


def uninstall_policy(browser_key: str = "") -> dict[str, Any]:
    from . import policy_install as _policy
    key = _resolve_key(browser_key)
    res = _policy.remove_policy(key)
    res["browserKey"] = key
    return res


def policy_artifacts(port: int) -> tuple[str, bytes, str]:
    """生成策略安装所需的 ``(update.xml 文本, crx 字节, 扩展 ID)``。

    桌面版的 HTTP 服务会把它暴露在
    ``/extension/update.xml`` 与 ``/extension/extension.crx``，
    也就是策略里的 update_url 指向的地方 —— **桌面版本身就是那个更新服务**。
    """
    from . import crx as _crx
    from . import policy_install as _policy

    ext_dir = stable_extension_dir(port)
    blob, eid, version = _policy.build_crx(ext_dir, port)
    url = f"http://127.0.0.1:{int(port)}/extension/extension.crx"
    return _crx.update_manifest_xml(eid, version, url), blob, eid
