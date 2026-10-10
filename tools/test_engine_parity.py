"""扩展 JS 引擎 与 桌面版 Python 引擎 的一致性交叉测试。

同一份 HTML 分别交给两边引擎，比对「最短唯一 XPath / CSS / 候选集 / 页面扫描 /
批量验证 / 校验结果」，确保浏览器扩展与桌面版行为一致。

用法：python tools/test_engine_parity.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NODE = r"C:\Users\Azu19\.workbuddy-ai\binaries\node\versions\22.22.2-6\node.exe"
NODE_MODULES = r"C:\Users\Azu19\.workbuddy-ai\binaries\node\workspace\node_modules"

from app import xpath_engine as E  # noqa: E402

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>示例商城</title></head>
<body>
  <header class="site-header">
    <a class="logo" href="/">MyShop</a>
    <nav class="main-nav"><ul>
      <li><a href="/phones" data-category="phones">手机</a></li>
      <li><a href="/laptops" data-category="laptops">笔记本</a></li>
    </ul></nav>
    <div class="header-actions">
      <button id="search-btn" class="icon-btn" aria-label="搜索">搜索</button>
      <a href="/cart" class="cart-link">购物车 <span class="cart-badge">3</span></a>
      <button id="login-btn" class="btn btn-primary active" type="button">登录</button>
    </div>
  </header>
  <main class="content">
    <section class="product-list">
      <article class="product-card" data-sku="A1001">
        <h3 class="product-title">无线降噪耳机 Pro</h3>
        <p class="price">¥ 899.00</p>
        <button class="add-to-cart" data-sku="A1001">加入购物车</button>
      </article>
      <article class="product-card" data-sku="A1002">
        <h3 class="product-title">智能手表 S8</h3>
        <p class="price">¥ 1,299.00</p>
        <button class="add-to-cart" data-sku="A1002">加入购物车</button>
      </article>
    </section>
    <form id="login-form" class="login-box" action="/login" method="post">
      <input id="username" name="username" type="text" placeholder="请输入用户名" required>
      <input id="password" name="password" type="password" placeholder="请输入密码" required>
      <button type="submit" class="btn btn-primary">登 录</button>
    </form>
    <div id="j_idt88:panel" class="sc-bdVTJa dKpMkN">动态元素</div>
    <form id="profile-form" class="profile-box">
      <label for="email">电子邮箱</label>
      <input id="email" type="email" class="form-control">
      <label>手机号码 <input name="phone" class="sc-bdVaJa text-sm"></label>
      <input data-testid="a1b2c3d4e5f6" class="plain-field">
      <button type="button" class="bg-red-500 hover:bg-red-600 text-2xl rounded-full btn-primary">保 存</button>
    </form>
  </main>
</body>
</html>"""

TARGETS = {
    "#login-btn": lambda root: _find(root, lambda e: e.attrib.get("id") == "login-btn"),
    ".add-to-cart": lambda root: _find(root, lambda e: "add-to-cart" in (e.attrib.get("class") or "")),
    "[id^='j_idt']": lambda root: _find(root, lambda e: (e.attrib.get("id") or "").startswith("j_idt")),
    "#username": lambda root: _find(root, lambda e: e.attrib.get("id") == "username"),
    ".cart-link": lambda root: _find(root, lambda e: "cart-link" in (e.attrib.get("class") or "")),
    ".product-title": lambda root: _find(root, lambda e: "product-title" in (e.attrib.get("class") or "")),
    # 标签锚定 / 测试属性 / 哈希 class 场景
    "[name=phone]": lambda root: _find(root, lambda e: e.attrib.get("name") == "phone"),
    "[data-testid]": lambda root: _find(root, lambda e: bool(e.attrib.get("data-testid"))),
    "#email": lambda root: _find(root, lambda e: e.attrib.get("id") == "email"),
}


def _find(root, pred):
    for el in root.iter():
        if isinstance(el.tag, str) and pred(el):
            return el
    return None


def run_js_probe() -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(HTML)
        path = f.name
    env = dict(os.environ)
    env["NODE_PATH"] = NODE_MODULES
    try:
        out = subprocess.run(
            [NODE, os.path.join(ROOT, "tools", "js_engine_probe.js"), path],
            capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT, timeout=120,
        )
    finally:
        os.unlink(path)
    if out.returncode != 0:
        print("JS 引擎探针执行失败：\n", out.stderr[:2000])
        sys.exit(1)
    return json.loads(out.stdout)


def run_py_engine() -> dict:
    root, index, tree, count, elements = E.load(HTML)
    res = {"gen": {}}
    for key, getter in TARGETS.items():
        el = getter(root)
        if el is None:
            continue
        r = E.gen_for_element(root, el, index)
        res["gen"][key] = {
            "best": r["best"],
            "css": r["css"],
            "playwright": [p["code"] for p in r["playwright"]],
            "candidates": [
                {"xpath": c["xpath"], "strategy": c["strategy"], "count": c["count"],
                 "unique": c["unique"], "score": c["score"], "level": c["level"]}
                for c in r["xpath"]
            ],
            "targetTag": r["target"]["tag"],
            "dynamicId": r["target"]["dynamicId"],
        }
    res["scan"] = [{"xpath": i["xpath"], "score": i["score"], "tag": i["tag"]} for i in E.scan_page(root, index)["items"]]
    res["verify"] = [
        {"selector": r["selector"], "type": r["type"], "valid": r["valid"], "count": r["count"]}
        for r in E.verify_batch(root, index, [
            "//button[@id='login-btn']", ".add-to-cart", "//div[@id='nope']",
            "#login-form input[name='username']", "//a[@href='/cart']",
        ])["results"]
    ]
    v = E.validate(root, index, "//button[@id='login-btn']")
    res["validate"] = {"valid": v["valid"], "count": v["count"]}
    bad = E.validate(root, index, "//div[@@bad")
    res["validateBad"] = {"valid": bad["valid"], "error": bad["error"]}
    btn = _find(root, lambda e: e.attrib.get("id") == "login-btn")
    res["minimalLoginBtn"] = E.minimal_xpath(btn, root)[0]
    res["absoluteLoginBtn"] = E.absolute_xpath(btn)

    # 新策略：标签锚定 / 测试属性
    email = _find(root, lambda e: e.attrib.get("id") == "email")
    phone = _find(root, lambda e: e.attrib.get("name") == "phone")
    tid = _find(root, lambda e: bool(e.attrib.get("data-testid")))
    res["labelText"] = [E._label_text_for(email, root), E._label_text_for(phone, root)]
    res["labelAnchors"] = [x for x, _m in E.label_anchored_xpaths(phone, root)]
    res["testidCands"] = [
        [c["xpath"], c["score"], c["unique"]]
        for c in E.gen_for_element(root, tid, index)["xpath"] if c["strategy"] == "testid"
    ]

    # 自愈建议（对着改版后的选择器）
    heal_selectors = [
        "//button[@id='login-btn-v2']",
        "//a[contains(concat(' ', normalize-space(@class), ' '), ' cart-link-old ')]",
        "//input[@name='user_name']",
        ".add-to-cart-legacy",
        "//button[normalize-space(text())='登 录一下']",
        "//div[@class='totally-absent']",
    ]
    res["heal"] = [
        {
            "selector": r["selector"],
            "count": r["count"],
            "heal": [[h["xpath"], h["score"], h["confidence"], h["reason"]] for h in r["heal"]],
        }
        for r in E.verify_batch(root, index, heal_selectors)["results"]
    ]
    res["healPure"] = {
        "simLoginBtn": E._round3(E._similar_text("login-btn", "login-button")),
        "simRegister": E._round3(E._similar_text("login-btn", "register-btn")),
        "simCjk": E._round3(E._similar_text("登录", "立即登录")),
        "simCjkSpace": E._round3(E._similar_text("登录", "登 录")),
        "hints": E.parse_selector_hints(
            "//a[contains(concat(' ', normalize-space(@class), ' '), ' cart-link ')]"),
        "cssHints": E.parse_css_hints("#login-btn .cart-link"),
    }
    return res


def main() -> int:
    print("=" * 62)
    print(" JS 引擎 vs Python 引擎 一致性测试")
    print("=" * 62)

    js = run_js_probe()
    py = run_py_engine()

    fails: list[str] = []
    warns: list[str] = []

    def check(name: str, a, b):
        if a == b:
            print(f"  ✓ {name}")
        else:
            print(f"  ✕ {name}\n      JS: {a!r}\n      PY: {b!r}")
            fails.append(name)

    if js.get("errors"):
        for e in js["errors"]:
            print(f"  ✕ JS 异常: {e}")
            fails.append("js-error")

    print("\n[1] 最短唯一 XPath")
    for key in py["gen"]:
        check(key, js["gen"].get(key, {}).get("best"), py["gen"][key]["best"])

    print("\n[2] CSS 选择器")
    for key in py["gen"]:
        check(key, js["gen"].get(key, {}).get("css", {}).get("css"), py["gen"][key]["css"]["css"])

    print("\n[3] Playwright 定位器")
    for key in py["gen"]:
        check(key, js["gen"].get(key, {}).get("playwright"), py["gen"][key]["playwright"])

    print("\n[4] 候选 XPath 集合（xpath -> score）")
    for key in py["gen"]:
        jm = {c["xpath"]: c["score"] for c in js["gen"].get(key, {}).get("candidates", [])}
        pm = {c["xpath"]: c["score"] for c in py["gen"][key]["candidates"]}
        only_js = sorted(set(jm) - set(pm))
        only_py = sorted(set(pm) - set(jm))
        diff_score = sorted(k for k in set(jm) & set(pm) if jm[k] != pm[k])
        if not only_js and not only_py and not diff_score:
            print(f"  ✓ {key}（{len(pm)} 条候选完全一致）")
        else:
            print(f"  ✕ {key}: 仅JS={only_js} 仅PY={only_py} 分数不同={diff_score}")
            fails.append("candidates:" + key)

    print("\n[5] 页面扫描")
    js_scan = sorted(i["xpath"] for i in js.get("scan", []))
    py_scan = sorted(i["xpath"] for i in py["scan"])
    if js_scan == py_scan:
        print(f"  ✓ 扫描结果一致（{len(py_scan)} 个可交互元素）")
    else:
        print(f"  ✕ 扫描不一致\n      仅JS: {sorted(set(js_scan) - set(py_scan))}\n      仅PY: {sorted(set(py_scan) - set(js_scan))}")
        fails.append("scan")

    print("\n[6] 批量验证")
    for i, r in enumerate(py["verify"]):
        j = js["verify"][i] if i < len(js.get("verify", [])) else {}
        check(f"{r['selector']} [{r['type']}]", (j.get("type"), j.get("valid"), j.get("count")),
              (r["type"], r["valid"], r["count"]))

    print("\n[7] 校验 / 最短路径 / 绝对路径")
    check("validate 正常", js.get("validate"), py["validate"])
    check("validate 非法", (js.get("validateBad") or {}).get("valid"), py["validateBad"]["valid"])
    check("minimalXPath(login-btn)", js.get("minimalLoginBtn"), py["minimalLoginBtn"])
    check("absoluteXPath(login-btn)", js.get("absoluteLoginBtn"), py["absoluteLoginBtn"])

    print("\n[8] 纯函数单元测试")
    pure = js.get("pure", {})
    check("动态值识别", pure.get("dynamic"), [True, False, True, False, True])
    check("新增动态模式（Angular/React useId/纯数字/Ember）", pure.get("dynamic2"),
          [E.is_dynamic_value(v)[0] for v in
           ["_ngcontent-c0", "_nghost-c1", ":r1a:", "12345", "ember482", "username"]])
    check("状态 class 剔除", pure.get("classes"), E.stable_class_tokens("btn btn-primary active hover is-open"))
    check("CSS-in-JS 哈希剔除", pure.get("classesHash"), E.stable_class_tokens("sc-bdVTJa dKpMkN"))
    check("哈希 token 判定", pure.get("hashy"),
          [E._is_hashy_token(t) for t in
           ["dKpMkN", "sc-bdVaJa", "css-1q2w3e", "svelte-1a2b3c", "bg-red-500",
            "text-2xl", "rounded-full", "container", "grid-cols-3"]])
    check("Tailwind 工具类保留 / 状态变体剔除", pure.get("classesTailwind"),
          E.stable_class_tokens("bg-red-500 hover:bg-red-600 text-2xl rounded-full btn-primary"))
    check("稳定性评级", pure.get("label"),
          [E.stability_label(88), E.stability_label(60), E.stability_label(20)])
    check("XPath 字面量转义", pure.get("literal"),
          [E._lit("a'b"), E._lit('a"b'), E._lit("a'b\"c")])

    print("\n[9] 标签锚定 / 测试属性（新策略）")
    check("label 文案（for= 显式关联）", pure.get("labelText", [None, None])[0], py["labelText"][0])
    check("label 文案（label 包裹）", pure.get("labelText", [None, None])[1], py["labelText"][1])
    check("标签锚定候选", pure.get("labelAnchors"), py["labelAnchors"])
    check("data-testid 形似哈希仍然被信任", pure.get("testidCands"), py["testidCands"])

    print("\n[10] 定位器自愈建议（Healenium 式）")
    hp = js.get("healPure", {})
    check("相似度函数", hp.get("simLoginBtn"), py["healPure"]["simLoginBtn"])
    check("相似度函数（不相干）", hp.get("simRegister"), py["healPure"]["simRegister"])
    check("相似度函数（中文）", hp.get("simCjk"), py["healPure"]["simCjk"])
    check("相似度函数（中文带空格）", hp.get("simCjkSpace"), py["healPure"]["simCjkSpace"])
    check("XPath 提示解析", hp.get("hints"), py["healPure"]["hints"])
    check("CSS 提示解析", hp.get("cssHints"), py["healPure"]["cssHints"])
    for i, r in enumerate(py["heal"]):
        j = js["heal"][i] if i < len(js.get("heal", [])) else {}
        check(f"自愈：{r['selector']}", j.get("heal"), r["heal"])
    # 至少要有一条真的给出了建议，否则测试是「假通过」
    healed = sum(1 for r in py["heal"] if r["heal"])
    if healed >= 4:
        print(f"  ✓ 有 {healed}/{len(py['heal'])} 条失配选择器给出了替代建议")
    else:
        print(f"  ✕ 自愈覆盖不足：只有 {healed} 条给出建议")
        fails.append("heal-coverage")

    print("\n" + "=" * 62)
    if fails:
        print(f" 结果：{len(fails)} 项不一致 ✕")
        for f in fails:
            print("   -", f)
        return 1
    print(" 结果：全部一致 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
