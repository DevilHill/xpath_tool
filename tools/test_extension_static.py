"""浏览器扩展静态一致性检查。

浏览器环境无法在沙箱内启动，因此用静态分析覆盖最容易出错的集成点：
  1. manifest 引用的文件是否都存在
  2. 用到的 chrome.* API 是否被 permissions / 顶层键覆盖
  3. 消息 type 在 content.js 与 background.js 之间是否对得上
  4. content.js 调用的 Engine.* / Panel.* 是否真的导出
  5. ui.js 中 data-role 与 q("...") 是否一一对应
  6. content.js 提供给面板的回调与 ui.js 期望的是否一致

用法：python tools/test_extension_static.py
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")

fails: list[str] = []


def ok(msg: str) -> None:
    print("  ✓", msg)


def bad(msg: str) -> None:
    print("  ✕", msg)
    fails.append(msg)


def read(rel: str) -> str:
    with open(os.path.join(EXT, rel), encoding="utf-8") as f:
        return f.read()


def main() -> int:
    print("=" * 62)
    print(" 浏览器扩展静态一致性检查")
    print("=" * 62)

    # ---- 1. manifest 文件引用 ----
    print("\n[1] manifest 引用的文件")
    with open(os.path.join(EXT, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    refs: list[str] = []
    refs.append(m["background"]["service_worker"])
    for cs in m.get("content_scripts", []):
        refs.extend(cs.get("js", []))
        refs.extend(cs.get("css", []))
    for key in ("icons",):
        refs.extend((m.get(key) or {}).values())
    refs.extend((m.get("action", {}).get("default_icon") or {}).values())
    missing = sorted({r for r in refs if not os.path.exists(os.path.join(EXT, r))})
    if missing:
        bad(f"manifest 引用但不存在: {missing}")
    else:
        ok(f"全部 {len(set(refs))} 个引用文件均存在")

    # ---- 2. 权限覆盖 ----
    print("\n[2] chrome.* API 与权限")
    bg = read("background.js")
    ct = read("content.js")
    ui = read("ui.js")
    perms = set(m.get("permissions", []))
    api_perm = {
        "chrome.scripting": "scripting",
        "chrome.webNavigation": "webNavigation",
        "chrome.storage": "storage",
        "chrome.alarms": "alarms",
        "chrome.action": None,
        "chrome.commands": None,
        "chrome.tabs": None,
        "chrome.runtime": None,
    }
    used = set(re.findall(r"chrome\.(\w+)\.", bg + ct + ui))
    unknown = sorted(a for a in used if f"chrome.{a}" not in api_perm)
    if unknown:
        bad(f"使用了未识别的 chrome API: {unknown}")
    else:
        ok(f"chrome API 使用: {sorted('chrome.' + u for u in used)}")
    need = {api_perm[f"chrome.{a}"] for a in used if api_perm.get(f"chrome.{a}")}
    lack = sorted(need - perms)
    if lack:
        bad(f"缺少权限声明: {lack}")
    else:
        ok(f"权限声明覆盖完整: {sorted(perms)}")

    # ---- 3. 消息 type 对齐 ----
    # 注意：background 里还有一类「发给桌面版」的 WS 协议消息（hello/status/picked…），
    # 它们不经过内容脚本，所以这里只统计真正通过 sendMessage/sendToTab 投递的类型。
    print("\n[3] 消息 type 对齐")

    def types_after(src: str, call_re: str) -> set[str]:
        """在压平后的源码里，找某个调用之后紧跟的 type 字面量。"""
        flat = re.sub(r"\s+", " ", src)
        return set(re.findall(call_re, flat))

    sent = types_after(ct, r'sendMessage\([^;]{0,200}?type:\s*"([a-z-]+)"') \
        | types_after(ui, r'sendMessage\([^;]{0,200}?type:\s*"([a-z-]+)"')
    handled_bg = set(re.findall(r'msg\.type\s*===\s*"([a-z-]+)"', bg))
    handled_ct = set(re.findall(r'msg\.type\s*===\s*"([a-z-]+)"', ct))
    orphan = sorted(sent - handled_bg)
    if orphan:
        bad(f"content 发送但后台无人处理: {orphan}")
    else:
        ok(f"content -> background 消息均有处理: {sorted(sent)}")

    back_sent = types_after(bg, r'(?:sendToTab|notifyTabs)\([^;]{0,200}?type:\s*"([a-z-]+)"')
    unhandled = sorted(back_sent - handled_ct)
    if unhandled:
        bad(f"background 发送但 content 未处理: {unhandled}")
    else:
        ok(f"background -> content 消息均有处理: {sorted(back_sent) or '无'}")

    # ---- 4. Engine.* / Panel.* 导出 ----
    print("\n[4] Engine / Panel 导出与调用")
    eng = read(os.path.join("lib", "engine.js"))
    eng_exports = set(re.findall(r"^\s{4}(\w+):\s", eng, re.M))
    called_eng = set(re.findall(r"Engine\.(\w+)", ct))
    miss_eng = sorted(called_eng - eng_exports)
    if miss_eng:
        bad(f"content.js 调用了未导出的 Engine.{miss_eng}")
    else:
        ok(f"Engine 调用全部存在（{len(called_eng)} 个）")

    panel_exports = set(re.findall(r"^\s{4}(\w+):\s", ui, re.M))
    called_panel = set(re.findall(r"Panel\.(\w+)", ct))
    miss_panel = sorted(called_panel - panel_exports)
    if miss_panel:
        bad(f"content.js 调用了未导出的 Panel.{miss_panel}")
    else:
        ok(f"Panel 调用全部存在（{len(called_panel)} 个）")

    # ---- 5. data-role 与 q() ----
    print("\n[5] 面板 data-role 与 q() 引用")
    roles_def = set(re.findall(r'data-role="([\w-]+)"', ui))
    roles_used = set(re.findall(r'q\("([\w-]+)"\)', ui))
    miss_role = sorted(roles_used - roles_def)
    if miss_role:
        bad(f"ui.js 里 q() 引用了不存在的 data-role: {miss_role}")
    else:
        ok(f"data-role 定义 {len(roles_def)} 个，q() 引用全部命中")

    # ---- 6. 面板回调 ----
    print("\n[6] 面板回调对接")
    expected = set(re.findall(r"state\.handlers\.(\w+)", ui))
    provided = set(re.findall(r"^\s{6}(\w+):\s", ct, re.M))
    miss_cb = sorted(expected - provided)
    if miss_cb:
        bad(f"ui.js 期望但 content.js 未提供: {miss_cb}")
    else:
        ok(f"回调全部对接（{len(expected)} 个）")

    # ---- 7. 其它文件 ----
    print("\n[7] 其它")
    if os.path.exists(os.path.join(EXT, "welcome.html")):
        ok("welcome.html 存在（安装后引导页）")
    else:
        bad("缺少 welcome.html（background 会打开它）")
    if m.get("default_locale"):
        has_locale = os.path.isdir(os.path.join(EXT, "_locales"))
        if has_locale:
            ok("default_locale 已声明且 _locales 存在")
        else:
            bad("声明了 default_locale 但没有 _locales 目录，扩展会加载失败")
    else:
        ok("未声明 default_locale（无需 _locales）")

    # ---- 8. WebSocket 桥接 ----
    print("\n[8] WebSocket 桥接")
    hp = " ".join(m.get("host_permissions", []))
    if "ws://127.0.0.1" in hp and "ws://localhost" in hp:
        ok("host_permissions 声明了 ws://127.0.0.1 与 ws://localhost")
    else:
        bad("host_permissions 缺少 ws:// 授权，扩展无法连接桌面版实时通道")

    if "new WebSocket(" in bg:
        ok("background.js 建立了 WebSocket 连接")
    else:
        bad("background.js 未建立 WebSocket 连接")

    for t in ("start-pick", "stop-pick"):
        if f'"{t}"' in bg and f'"{t}"' in ct:
            ok(f"桥接指令 {t} 在 background / content 两端一致")
        else:
            bad(f"桥接指令 {t} 未在两端同时出现")

    if 'role: "extension"' in bg:
        ok("background.js 以 extension 角色注册（桌面版据此识别来源）")
    else:
        bad("background.js 未声明 role: extension")

    if "api/bridge/result" in bg:
        ok("background.js 有 HTTP 兜底回传通道（/api/bridge/result）")
    else:
        bad("background.js 缺少 HTTP 兜底回传通道")

    if "ctrlKey" in ct and "metaKey" in ct:
        ok("content.js 使用 Ctrl（Mac 为 Cmd）+ 左键 作为选中手势")
    else:
        bad("content.js 未实现 Ctrl+左键 选中手势")

    if "__xpath_studio_overlay__" in ct:
        ok("content.js 使用独立覆盖层（不依赖面板是否打开）")
    else:
        bad("content.js 缺少独立覆盖层，桌面版驱动时无法高亮")

    print("\n" + "=" * 62)
    if fails:
        print(f" 结果：{len(fails)} 项问题 ✕")
        return 1
    print(" 结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
