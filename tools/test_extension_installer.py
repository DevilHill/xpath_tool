"""扩展一键安装模块的自检。

**绝对不真的启动浏览器**：所有会 `Popen` 的地方都被替换成记录器，
CDP 调试端口和「扩展是否连回来」也都被替换掉。这样测试跑起来是纯离线的。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import extension_installer as ei  # noqa: E402

PASS = 0
FAIL = 0
NOTES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  -> {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title} ==")


# --------------------------------------------------------------------------- #
section("1. 浏览器探测")
# 本机禁止注册表探测：这里只用明确的浏览器路径与PE版本，缺省时使用桩。
real_read_app_path, real_registry_version = ei._read_app_path, ei._registry_version
ei._read_app_path = lambda rel: ""
ei._registry_version = lambda key: ""
browsers = ei.find_browsers()
ei._read_app_path, ei._registry_version = real_read_app_path, real_registry_version
check("find_browsers 返回 list", isinstance(browsers, list), type(browsers).__name__)
for b in browsers:
    keys = {"key", "name", "path", "version", "major", "branded", "cdp", "flag", "recommend", "note"}
    check(f"{b['key']} 字段齐全", keys <= set(b.keys()), str(sorted(keys - set(b.keys()))))
    check(f"{b['key']} recommend 合法", b["recommend"] in ("cdp", "flag", "guided"), b["recommend"])
    check(f"{b['key']} path 存在", os.path.exists(b["path"]), b["path"])
    check(f"{b['key']} 版本可解析", b["major"] > 0, b["version"])
    NOTES.append(f"{b['key']} {b['version']} recommend={b['recommend']} flag={b['flag']} cdp={b['cdp']}")

# 品牌版 Chrome 137+ 必须 flag=False（这是整个模块存在的理由）
for b in browsers:
    if b["branded"] and b["major"] >= ei.CHROME_FLAG_REMOVED_AT:
        check(f"{b['key']} 137+ 已禁用 flag", b["flag"] is False)
        check(f"{b['key']} 默认推荐现有浏览器引导", b["recommend"] == "guided", b["recommend"])


# --------------------------------------------------------------------------- #
section("2. 版本号解析")
check("_major 解析 '151.0.7922.76'", ei._major("151.0.7922.76") == 151)
check("_major 解析 'Google Chrome 153.0.8010.53'", ei._major("Google Chrome 153.0.8010.53") == 153)
check("_major 解析 'Microsoft Edge/154.0.4258.37'", ei._major("Microsoft Edge/154.0.4258.37") == 154)
check("_major 空串 -> 0", ei._major("") == 0)
check("_major 垃圾输入 -> 0", ei._major("正在现有的浏览器会话中打开。") == 0)

if browsers:
    exe = browsers[0]["path"]
    v = ei._pe_file_version(exe)
    check("PE 文件版本可读", bool(v) and "." in v, v)
    check("PE 版本与探测一致", v.split(".")[0] == str(browsers[0]["major"]), f"{v} vs {browsers[0]['major']}")


# --------------------------------------------------------------------------- #
section("3. 浏览器选择")
if len(browsers) >= 2:
    target = browsers[1]["key"]
    check("pick_browser 指定 key 生效", (ei.pick_browser(browsers, target) or {}).get("key") == target)
check("pick_browser 空列表 -> None", ei.pick_browser([]) is None)
check("pick_browser 未知 key 有兜底", ei.pick_browser(browsers, "no-such-browser") is not None)
if browsers:
    pref = ei.pick_browser(browsers)
    check("pick_browser 默认优先 chrome", pref["key"] == "chrome" or not any(b["key"] == "chrome" for b in browsers), str(pref["key"]))


# --------------------------------------------------------------------------- #
section("4. 扩展目录")
src = ei._bundle_dir()
check("_bundle_dir 找到 extension/", src is not None and src.is_dir(), str(src))
if src:
    check("含 manifest.json", (src / "manifest.json").is_file())
    check("含 background.js", (src / "background.js").is_file())
    check("含 lib/engine.js", (src / "lib" / "engine.js").is_file())
    try:
        mf = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        check("manifest 是合法 JSON", isinstance(mf, dict))
        check("manifest_version == 3", mf.get("manifest_version") == 3)
        check("manifest 有 permissions", isinstance(mf.get("permissions"), list))
        check("manifest 有 host_permissions", isinstance(mf.get("host_permissions"), list))
    except Exception as exc:  # noqa: BLE001
        check("manifest 可解析", False, str(exc))

d1 = ei.stable_extension_dir(8790)
check("stable_extension_dir 返回存在的目录", Path(d1).is_dir(), str(d1))
check("源码运行时直接用项目目录", str(d1) == str(src), f"{d1} vs {src}")


# --------------------------------------------------------------------------- #
section("5. 端口改写（打包副本专用）")
import shutil  # noqa: E402
import tempfile  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="xps-ext-", dir=ROOT / "build"))
try:
    if src:
        shutil.copytree(src, tmp / "extension")
        ei._patch_bridge_port(tmp / "extension", 8123)
        bg = (tmp / "extension" / "background.js").read_text(encoding="utf-8")
        check("默认桥接端口已改写为 8123", "http://127.0.0.1:8123" in bg)
        check("旧端口 8790 不再出现", "http://127.0.0.1:8790" not in bg)
        ei._patch_bridge_port(tmp / "extension", 8791)
        bg2 = (tmp / "extension" / "background.js").read_text(encoding="utf-8")
        check("可重复改写（幂等，不叠加）", bg2.count("var DEFAULT_BRIDGE") == 1)
        source, dest = tmp / "source", tmp / "dest"
        source.mkdir(); dest.mkdir()
        (source / "manifest.json").write_text('{"version":"1.2.0"}', encoding="utf-8")
        (dest / "manifest.json").write_text('{"version":"1.1.0"}', encoding="utf-8")
        ei._sync_tree(source, dest)
        check("同大小清单也更新内容", (dest / "manifest.json").read_bytes() == (source / "manifest.json").read_bytes())
        from unittest.mock import patch
        (source / "manifest.json").write_text('{"version":"1.3.0"}', encoding="utf-8")
        raised = False
        with patch.object(ei.shutil, "copy2", side_effect=PermissionError("blocked")):
            try: ei._sync_tree(source, dest)
            except OSError: raised = True
        check("复制失败不会吞异常报成功", raised)
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
section("6. 策略解析（不启动浏览器）")
spawned: list[list[str]] = []
real_spawn = ei._spawn
real_wait_ext = ei.wait_for_extension
real_wait_dbg = ei._wait_debugger
real_find = ei.find_browsers
real_clip = ei.clipboard_set
real_profile = ei._profile_dir
profile_tmp = Path(tempfile.mkdtemp(prefix="installer-test-", dir=ROOT / "build"))

try:
    ei._spawn = lambda exe, args: spawned.append([exe, *args])
    ei.clipboard_set = lambda text: True
    ei._profile_dir = lambda key, suffix="": profile_tmp / (key + suffix)

    fake = [
        {"key": "chrome", "name": "Google Chrome", "path": "C:/x/chrome.exe", "version": "153.0.0.0",
         "major": 153, "branded": True, "cdp": True, "flag": False, "recommend": "cdp", "note": "n"},
        {"key": "edge", "name": "Microsoft Edge", "path": "C:/x/msedge.exe", "version": "154.0.0.0",
         "major": 154, "branded": False, "cdp": True, "flag": True, "recommend": "flag", "note": ""},
    ]
    ei.find_browsers = lambda: fake
    ei.wait_for_extension = lambda timeout=30.0, interval=0.5: True

    # 默认必须进入现有浏览器，即使旧客户端推荐 flag/cdp 也不隐式启动独立实例。
    spawned.clear()
    r = ei.install(strategy="auto", browser_key="edge", verify_timeout=1)
    check("auto+edge 选 guided", r.get("strategy") == "guided", str(r.get("strategy")))
    check("auto 不指定独立 profile 或调试端口", spawned[0] == [fake[1]["path"], "edge://extensions/"], str(spawned))
    check("auto 标记现有浏览器且安装未验证", r.get("target") == "existing" and r.get("installationVerified") is False)
    check("多个人资料时提示确认目标窗口", any("个人资料" in s for s in r.get("steps", [])))
    spawned.clear()
    r = ei.install(strategy="flag", browser_key="edge", verify_timeout=1)
    check("flag 命令行带 --load-extension", any("--load-extension" in a for a in spawned[0]))
    check("flag 使用独立 profile", any(a.startswith("--user-data-dir=") for a in spawned[0]))
    check("flag 无调试端口", not any("--remote-debugging-port" in a for a in spawned[0]))
    check("flag 结果标记已连接", r.get("connected") is True)

    # auto -> chrome 必须打开现有浏览器扩展页；高级 CDP 仍保留兜底。
    spawned.clear()
    ei._wait_debugger = lambda port, timeout=25.0: ""
    r = ei.install(strategy="auto", browser_key="chrome", verify_timeout=1)
    check("chrome auto 选 guided", r.get("strategy") == "guided", str(r.get("strategy")))
    check("chrome auto 不创建独立实例", spawned[0] == [fake[0]["path"], "chrome://extensions/"], str(spawned))
    spawned.clear()
    r = ei.install(strategy="cdp", browser_key="chrome", verify_timeout=1)
    check("显式选择 cdp 标记独立实例", r.get("target") == "isolated")
    check("cdp 命令行带调试端口", any("--remote-debugging-port=" in a for a in spawned[0]))
    check("cdp 命令行带 unsafe-extension-debugging", any("--enable-unsafe-extension-debugging" in a for a in spawned[0]))
    check("调试端口不可用时失败", r.get("ok") is False, str(r.get("ok")))
    check("失败时给出 guided 兜底", r.get("fallback") == "guided", str(r.get("fallback")))

    # 强制 flag 但浏览器禁用 flag -> 自动降级到 cdp
    spawned.clear()
    ei._wait_debugger = lambda port, timeout=25.0: ""
    r = ei.install(strategy="flag", browser_key="chrome", verify_timeout=1)
    check("chrome 强制 flag 被降级为 cdp", r.get("strategy") == "cdp", str(r.get("strategy")))

    # guided：打开扩展页 + 剪贴板
    spawned.clear()
    r = ei.install(strategy="guided", browser_key="edge", verify_timeout=1)
    check("guided 成功", r.get("ok") is True and r.get("guided") is True, str(r))
    check("Edge引导打开edge://extensions/", "edge://extensions/" in spawned[0])
    check("guided 复制了扩展目录", r.get("copied") is True)
    check("guided 有步骤说明", isinstance(r.get("steps"), list) and len(r["steps"]) >= 3)
    check("guided 不做连接校验", "connected" not in r)

    # 没有浏览器
    ei.find_browsers = lambda: []
    r = ei.install(strategy="auto", verify_timeout=1)
    check("无浏览器时报错清晰", r.get("ok") is False and "浏览器" in r.get("error", ""), str(r.get("error")))

    # 浏览器启动了但扩展没连回来 -> warning + fallback
    ei.find_browsers = lambda: fake
    ei.wait_for_extension = lambda timeout=30.0, interval=0.5: False
    ei._wait_debugger = lambda port, timeout=25.0: ""
    spawned.clear()
    r = ei.install(strategy="flag", browser_key="edge", verify_timeout=1)
    check("未连回时 ok 仍为 True（命令成功）", r.get("ok") is True)
    check("未连回时 connected=False", r.get("connected") is False)
    check("未连回时给出 warning", bool(r.get("warning")))
    check("未连回时给出 guided 兜底", r.get("fallback") == "guided")

    from app import policy_install as pi
    from unittest.mock import patch
    with patch.object(pi, "install_policy", return_value={"ok": False, "error": "denied"}):
        r = ei.install("policy", "chrome")
    check("策略失败不要求重启", r.get("needsRestart") is False)
    check("策略失败仍提供引导退路", r.get("fallback") == "guided")
    with patch.object(pi, "install_policy", return_value={"ok": True}):
        r = ei.install("policy", "chrome")
    check("策略写入不标为已验证安装", r.get("policyConfigured") is True and r.get("installationVerified") is False)
    with patch.object(ei, "_spawn", side_effect=OSError("launch denied")):
        r = ei.install("guided", "edge")
    check("打开引导页失败不报成功", r.get("ok") is False and r.get("stage") == "guided-open")
    check("打开引导页失败仍提供手工地址和目录", r.get("managementUrl") == "edge://extensions/" and bool(r.get("extDir")))
    check("未知浏览器不改装其它浏览器", ei.install("policy", "absent").get("stage") == "browser-detect")

finally:
    ei._profile_dir = real_profile
    shutil.rmtree(profile_tmp, ignore_errors=True)
    ei._spawn = real_spawn
    ei.wait_for_extension = real_wait_ext
    ei._wait_debugger = real_wait_dbg
    ei.find_browsers = real_find
    ei.clipboard_set = real_clip


# --------------------------------------------------------------------------- #
print("\n" + "-" * 60)
print(f"通过 {PASS} / 失败 {FAIL}")
for n in NOTES:
    print("  · " + n)
sys.exit(1 if FAIL else 0)
