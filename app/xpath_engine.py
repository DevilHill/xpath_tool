"""XPath 规则引擎（v2）。

参考并吸收了以下开源项目的思路：
  * Robula+ (Leotta et al.)        —— 最短唯一 XPath：从绝对路径逐步削减前缀步骤
  * xpath-helper-plus (mic1on)     —— class token 匹配、剔除运行时状态 class、位置索引语义
  * XPath Forte                    —— 稳定性评分模型、动态 ID 识别、多类型定位器

能力：
  * HTML/XML 解析、DOM 树导出
  * XPath 校验（lxml XPath 1.0 引擎）
  * 节点 -> 候选 XPath（含最短唯一解、列表模式）+ 稳定性评分
  * 节点 -> CSS 选择器 / Playwright 定位器
  * 自然语言离线检索、页面可交互元素扫描、批量定位器验证
"""
from __future__ import annotations

import math
import re
from typing import Any

from lxml import etree
from lxml import html as lhtml

try:  # CSS 选择器校验（可选依赖）
    import cssselect  # noqa: F401

    _HAS_CSSSELECT = True
except Exception:  # noqa: BLE001
    _HAS_CSSSELECT = False


# --------------------------------------------------------------------------- #
# 常量：动态值识别 / 不稳定 class / 属性优先级
# --------------------------------------------------------------------------- #
_DYNAMIC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^j_idt?\d", re.I), "JSF 动态 ID"),
    (re.compile(r"^j_id", re.I), "JSF 动态 ID"),
    (re.compile(r"^ng-", re.I), "Angular 生成"),
    (re.compile(r"^_ngcontent", re.I), "Angular 视图封装"),
    (re.compile(r"^_nghost", re.I), "Angular 视图封装"),
    (re.compile(r"^data-v-", re.I), "Vue scoped 标记"),
    (re.compile(r"^sc-[A-Za-z0-9]{4,}", re.I), "styled-components 哈希"),
    (re.compile(r"^css-[a-z0-9]{4,}", re.I), "emotion 哈希"),
    (re.compile(r"^mui-\d", re.I), "Material-UI 生成"),
    (re.compile(r"^svelte-", re.I), "Svelte scoped 哈希"),
    (re.compile(r"^ember\d", re.I), "Ember 生成"),
    (re.compile(r"^radix-", re.I), "Radix 生成"),
    (re.compile(r"^headlessui-", re.I), "HeadlessUI 生成"),
    (re.compile(r"^react-select-\d", re.I), "react-select 生成"),
    # React 18 useId：id 形如 ":r1a:" / ":R2b:"，冒号在 XPath 里还必须转义，一律判动态
    (re.compile(r"^:r[0-9a-z]+:$", re.I), "React useId"),
    # 纯数字 / 纯数字结尾的 id（列表项自增 id）
    (re.compile(r"^\d+$"), "纯数字"),
    (re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I), "UUID"),
    (re.compile(r"^[0-9a-f]{16,}$", re.I), "十六进制哈希"),
]

_UNSTABLE_CLASSES = {
    "active", "hover", "focus", "focused", "focus-visible", "selected", "checked",
    "open", "opened", "closed", "close", "show", "shown", "hide", "hidden",
    "visible", "invisible", "disabled", "enabled", "current", "loading", "loaded",
    "collapsed", "expanded", "dragging", "dragover", "animating", "animate",
    "on", "off", "error", "success", "warning", "invalid", "valid", "dirty",
    "is-active", "is-open", "is-selected", "is-hidden", "is-visible", "is-collapsed",
    "is-expanded", "is-loading", "is-disabled", "is-error", "is-success",
    "has-error", "has-success", "js-", "css-", "sr-only", "visually-hidden",
}

# Tailwind 的「状态变体」前缀（hover:bg-red-600 之类）：只影响观感，做定位器没意义。
# 响应式/暗色变体（sm: / md: / dark:）反而描述布局，保留。
_TAILWIND_STATE_VARIANT = re.compile(
    r"^(hover|focus|focus-within|focus-visible|active|visited|target|disabled|"
    r"checked|indeterminate|default|required|valid|invalid|placeholder-shown|"
    r"autofill|read-only|group-hover|group-focus|group-active|group-disabled|"
    r"peer-hover|peer-focus|peer-checked|before|after|first|last|odd|even):",
    re.I,
)

_STRATEGY_BASE = {
    "testid": 95,
    "id": 88,
    "semantic": 78,
    "label": 74,
    "ancestor": 76,
    "combo": 72,
    "text": 70,
    "attr": 66,
    "class": 60,
    "list": 66,
    "index": 40,
    "id_dynamic": 42,
    "path": 22,
}

# 这些属性是**专门为测试/自动化准备的**，即使长得像哈希也应当被信任。
# （见 parthsathwara22/xpath-generator-extension：data-testid 等一律视为稳定）
_TEST_ATTRS = ("data-testid", "data-test", "data-test-id", "data-qa", "data-cy", "data-automation-id")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def parse_html(source: str):
    text = source or ""
    if not text.strip():
        raise ValueError("内容为空，请先提供 HTML / XML 源码")

    root = None
    head = text.lstrip()[:400].lower()
    looks_xml = head.startswith("<?xml") or (
        head.startswith("<") and "<html" not in head and "<!doctype html" not in head
    )
    if looks_xml:
        try:
            root = etree.fromstring(text.encode("utf-8"), parser=etree.XMLParser(recover=True, huge_tree=True))
        except Exception:  # noqa: BLE001
            root = None
    if root is None:
        root = lhtml.fromstring(text, parser=lhtml.HTMLParser(recover=True, encoding="utf-8", huge_tree=True))
    return root


def _tag(el) -> str:
    tag = el.tag
    if isinstance(tag, str):
        return tag
    if tag is etree.Comment:
        return "#comment"
    if tag is etree.ProcessingInstruction:
        return "#pi"
    return "#node"


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _direct_text(el, limit: int = 80) -> str:
    return _norm(el.text or "")[:limit]


def _lit(s: str) -> str:
    """生成 XPath 字符串字面量，处理引号冲突。"""
    if "'" not in s:
        return "'" + s + "'"
    if '"' not in s:
        return '"' + s + '"'
    parts = s.split("'")
    out: list[str] = []
    for i, p in enumerate(parts):
        if i > 0:
            out.append("\"'\"")
        if p:
            out.append("'" + p + "'")
    return "concat(" + ", ".join(out) + ")"


def _chain(el) -> list:
    """从根到 el 的元素链（含根与自身）。"""
    nodes = []
    cur = el
    while cur is not None:
        nodes.append(cur)
        cur = cur.getparent()
    nodes.reverse()
    return nodes


def _xpath_of(root, xp: str):
    try:
        return root.xpath(xp)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# 动态值 / 稳定性
# --------------------------------------------------------------------------- #
def is_dynamic_value(value: str) -> tuple[bool, str]:
    v = (value or "").strip()
    if not v:
        return True, "空值"
    for pat, reason in _DYNAMIC_PATTERNS:
        if pat.search(v):
            return True, reason
    if len(v) >= 8:
        digits = sum(ch.isdigit() for ch in v)
        ratio = digits / len(v)
        if ratio > 0.6:
            return True, "数字占比过高"
        if re.search(r"\d{5,}$", v) and ratio > 0.4:
            return True, "以长数字结尾"
    return False, ""


def _is_hashy_token(t: str) -> bool:
    """判断 class token 是否像构建工具生成的哈希。

    两类（都要求「大小写/数字混杂」，避免误杀 Tailwind 的 ``bg-red-500``、
    ``text-2xl``、``space-y-4`` 这类稳定工具类）：

      1) 裸哈希：``dKpMkN``、``x7hF2``
      2) 前缀 + 哈希：``sc-bdVaJa``、``css-1q2w3e``、``svelte-1a2b3c``
    """
    if not t:
        return False

    bare = re.match(r"^[A-Za-z0-9]{5,10}$", t)
    if bare:
        if re.match(r"^[a-z]+$", t):
            return False                      # 全小写普通单词
        up = sum(c.isupper() for c in t)
        lo = sum(c.islower() for c in t)
        di = sum(c.isdigit() for c in t)
        return (up >= 2 and lo >= 2) or (up >= 1 and di >= 1) or (lo >= 2 and di >= 2)

    m = re.match(r"^([A-Za-z_]\w*-)([A-Za-z0-9]{4,})$", t)
    if not m:
        return False
    s = m.group(2)
    up = sum(c.isupper() for c in s)
    lo = sum(c.islower() for c in s)
    di = sum(c.isdigit() for c in s)
    return (up >= 2 and lo >= 2) or (lo >= 2 and di >= 2) or (up >= 1 and lo >= 1 and di >= 1)


def stable_class_tokens(class_str: str) -> list[str]:
    toks = [t for t in (class_str or "").split() if t]
    good = []
    for t in toks:
        if t.lower() in _UNSTABLE_CLASSES:
            continue
        if t.startswith("js-") or t.startswith("css-"):
            continue
        if _TAILWIND_STATE_VARIANT.match(t):
            continue
        dyn, _ = is_dynamic_value(t)
        if dyn and re.match(r"^[A-Za-z0-9_-]{8,}$", t) and not re.match(r"^[a-z]+(-[a-z]+)+$", t):
            continue
        # CSS-in-JS / scoped 哈希（dKpMkN、sc-bdVaJa、css-1q2w3e…）
        if _is_hashy_token(t):
            continue
        good.append(t)
    good.sort(key=lambda c: (-len(c), c))
    return good


def stability_label(score: int) -> str:
    if score >= 70:
        return "稳定"
    if score >= 45:
        return "一般"
    return "脆弱"


def _apply_penalty(score: int, xp: str, depth: int) -> int:
    # 绝对路径（/html/... 或 (/html/...）判为脆弱
    if re.match(r"^\(?\s*/html\b", xp):
        score = min(score, 20)
    # 以 //body 或 //html 开头的深层路径同样脆弱
    elif re.match(r"^//(body|html)\b", xp):
        score = min(score, 35)
    if re.search(r"\[\d+\]", xp):
        score = min(score, 40)
    if "sibling::" in xp:
        score = min(score, 50)
    if depth > 4:
        score -= min((depth - 4) * 5, 20)
    if "contains(text()" in xp or "contains(.," in xp:
        score -= 6
    return max(0, min(100, score))


# --------------------------------------------------------------------------- #
# DOM 树
# --------------------------------------------------------------------------- #
def build_tree(root):
    """返回 (tree, index, count, elements)。

    注意：lxml 的元素代理对象是临时创建的，若被 GC 回收，其 id() 会被复用，
    导致 id(el) -> idx 映射失效。因此这里把每个元素代理都存进 elements 列表
    保持强引用，保证后续 root.iter() / root.xpath() 返回的是同一批代理对象。
    """
    index: dict[int, int] = {}
    elements: list = []
    counter = {"n": 0}

    def walk(el) -> dict[str, Any]:
        i = counter["n"]
        counter["n"] += 1
        elements.append(el)          # 强引用，保证 id() 稳定
        index[id(el)] = i
        return {
            "idx": i,
            "tag": _tag(el),
            "attrs": {k: v for k, v in el.attrib.items() if not k.startswith("{")},
            "text": _direct_text(el),
            "children": [walk(c) for c in el],
        }

    tree = walk(root)
    return tree, index, counter["n"], elements


def describe(root) -> dict[str, Any]:
    tags: dict[str, int] = {}
    for el in root.iter():
        if isinstance(el.tag, str):
            tags[el.tag] = tags.get(el.tag, 0) + 1
    return {"total": sum(tags.values()), "top": sorted(tags.items(), key=lambda kv: -kv[1])[:8]}


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def _clean_err(exc: Exception) -> str:
    return str(exc).split("\n")[0].replace("Invalid expression", "无效表达式")


def validate(root, index: dict[int, int], xpath: str, limit: int = 500) -> dict[str, Any]:
    xpath = (xpath or "").strip()
    if not xpath:
        return {"valid": False, "error": "XPath 不能为空", "count": 0, "matches": []}
    try:
        result = root.xpath(xpath)
    except etree.XPathError as exc:
        return {"valid": False, "error": _clean_err(exc), "count": 0, "matches": []}
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "error": str(exc), "count": 0, "matches": []}

    if not isinstance(result, list):
        result = [result]
    matches: list[dict[str, Any]] = []
    for r in result:
        if isinstance(r, etree._Element):
            matches.append(
                {"idx": index.get(id(r)), "kind": "node", "tag": _tag(r), "attrs": dict(r.attrib), "text": _direct_text(r, 120)}
            )
        else:
            matches.append({"idx": None, "kind": "value", "value": str(r)})
    return {"valid": True, "count": len(matches), "matches": matches[:limit], "truncated": len(matches) > limit}


# --------------------------------------------------------------------------- #
# 谓词生成（Robula+ 式：优先能唯一定位兄弟节点的谓词）
# --------------------------------------------------------------------------- #
def _candidate_predicates(el) -> list[tuple[str, dict]]:
    """按稳健度从高到低产出候选谓词（Robula+ 式）。"""
    out: list[tuple[str, dict]] = []
    attrs = {k: v for k, v in el.attrib.items() if not k.startswith("{")}

    # 1) 测试专用属性（最稳健）。
    #    注意：这里**不做动态值判定** —— 这些属性就是给自动化用的，
    #    即便值看起来像哈希（如 data-testid="a1b2c3d4e5f6"）也应当信任。
    for a in _TEST_ATTRS:
        v = (attrs.get(a) or "").strip()
        if v:
            out.append((f"@{a}={_lit(v)}", {"strategy": "testid", "attr": a}))

    # 2) id
    if (attrs.get("id") or "").strip():
        v = attrs["id"]
        dyn, reason = is_dynamic_value(v)
        if dyn:
            out.append((f"@id={_lit(v)}", {"strategy": "id_dynamic", "attr": "id", "warn": f"疑似动态 ID（{reason}）"}))
        else:
            out.append((f"@id={_lit(v)}", {"strategy": "id", "attr": "id"}))

    # 3) 语义属性
    for a in ("name", "aria-label", "role", "placeholder", "alt", "title", "type", "value", "href"):
        v = (attrs.get(a) or "").strip()
        if not v or len(v) > 120:
            continue
        if is_dynamic_value(v)[0] and a not in ("type", "href", "role"):
            continue
        strat = "semantic" if a in ("name", "aria-label", "role") else "attr"
        out.append((f"@{a}={_lit(v)}", {"strategy": strat, "attr": a}))

    # 4) 其它 data-* 属性（如 data-sku / data-id）
    for a, raw in attrs.items():
        if not a.startswith("data-") or a in _TEST_ATTRS:
            continue
        v = (raw or "").strip()
        if v and len(v) <= 120 and not is_dynamic_value(v)[0]:
            out.append((f"@{a}={_lit(v)}", {"strategy": "attr", "attr": a}))

    # 5) 精确文本
    txt = _direct_text(el, 50)
    if txt:
        out.append((f"normalize-space(text())={_lit(txt)}", {"strategy": "text"}))

    # 6) class token（已剔除运行时状态 class）
    for c in stable_class_tokens(attrs.get("class", ""))[:4]:
        out.append((f"contains(concat(' ', normalize-space(@class), ' '), {_lit(' ' + c + ' ')})", {"strategy": "class", "cls": c}))

    # 7) 多属性组合
    simple = [a for a in ("name", "type", "role", "aria-label") if (attrs.get(a) or "").strip()]
    if len(simple) >= 2:
        out.append((" and ".join(f"@{a}={_lit(attrs[a])}" for a in simple[:2]), {"strategy": "combo"}))

    return out


def _step_for(el, parent) -> tuple[str, dict]:
    tag = _tag(el)
    for pred, meta in _candidate_predicates(el):
        try:
            r = parent.xpath(f"./{tag}[{pred}]")
        except Exception:  # noqa: BLE001
            continue
        if len(r) == 1 and r[0] is el:
            return f"{tag}[{pred}]", meta
    sibs = [s for s in parent if _tag(s) == tag]
    idx = (sibs.index(el) + 1) if el in sibs else 1
    return f"{tag}[{idx}]", {"strategy": "index"}


def _locates_only(root, xp: str, el) -> bool:
    res = _xpath_of(root, xp)
    return bool(res) and isinstance(res, list) and len(res) == 1 and res[0] is el


def minimal_xpath(el, root) -> tuple[str, int, dict]:
    """Robula+ 式最短唯一 XPath：先建完整路径，再从头部逐步削减。"""
    chain = _chain(el)
    if len(chain) == 1:
        return "/" + _tag(el), 1, {"strategy": "path"}

    steps: list[str] = []
    meta: dict = {"strategy": "path"}
    for node in chain[1:]:
        s, m = _step_for(node, node.getparent())
        steps.append(s)
        if node is el:
            meta = m

    # 从「最短后缀」开始试，找到第一个仍然唯一的即采用（Robula+ 的削减思路）
    chosen = steps
    for i in range(len(steps) - 1, -1, -1):
        trial = steps[i:]
        xp = "//" + "/".join(trial)
        if _locates_only(root, xp, el):
            chosen = trial
            break
    return "//" + "/".join(chosen), len(chosen), meta


def absolute_xpath(el) -> str:
    chain = _chain(el)
    parts = []
    for node in chain:
        parent = node.getparent()
        tag = _tag(node)
        if parent is None:
            parts.append(tag)
            continue
        sibs = [s for s in parent if _tag(s) == tag]
        parts.append(f"{tag}[{sibs.index(node) + 1}]" if len(sibs) > 1 else tag)
    return "/" + "/".join(parts)


def list_xpath(el, root) -> str:
    """列表模式：优先挑一个能匹配到多个同类元素的谓词（集合定位）。"""
    tag = _tag(el)
    best: tuple[int, str, int] | None = None
    for pred, m in _candidate_predicates(el):
        xp = f"//{tag}[{pred}]"
        res = _xpath_of(root, xp)
        if res and len(res) > 1:
            score = _STRATEGY_BASE.get(m.get("strategy", "attr"), 50)
            if best is None or score > best[0]:
                best = (score, xp, len(res))
    if best:
        return best[1]
    # 兜底：去掉最后一步的索引
    chain = _chain(el)
    if len(chain) == 1:
        return "//" + tag
    steps = []
    for node in chain[1:]:
        s, m = _step_for(node, node.getparent())
        if node is el and m.get("strategy") == "index":
            s = _tag(node)
        steps.append(s)
    xp = "//" + "/".join(steps)
    return xp if _xpath_of(root, xp) else ("//" + "/".join(steps[:-1]) if len(steps) > 1 else xp)


# --------------------------------------------------------------------------- #
# CSS / Playwright
# --------------------------------------------------------------------------- #
def _css_ident(s: str) -> str:
    return re.sub(r"([^\w-])", r"\\\1", s)


def _css_step(el) -> str:
    attrs = {k: v for k, v in el.attrib.items() if not k.startswith("{")}
    if attrs.get("id", "").strip() and not is_dynamic_value(attrs["id"])[0]:
        return "#" + _css_ident(attrs["id"])
    for a in ("data-testid", "data-test", "data-qa", "data-cy"):
        if attrs.get(a, "").strip():
            return f'[{a}="{attrs[a]}"]'
    tag = _tag(el)
    cls = stable_class_tokens(attrs.get("class", ""))[:2]
    if cls:
        return tag + "".join("." + _css_ident(c) for c in cls)
    for a in ("name", "aria-label", "placeholder", "type"):
        if attrs.get(a, "").strip():
            return f'{tag}[{a}="{attrs[a]}"]'
    return tag


def _css_count(root, css: str):
    if not _HAS_CSSSELECT:
        return None
    try:
        return len(root.cssselect(css))
    except Exception:  # noqa: BLE001
        return None


def gen_css(el, root) -> dict[str, Any]:
    chain = _chain(el)[1:]
    if not chain:
        return {"css": _tag(el), "count": 1, "unique": True, "score": 30, "level": "脆弱"}
    parts = [_css_step(n) for n in chain]
    chosen = parts
    for i in range(len(parts) - 1, -1, -1):
        trial = parts[i:]
        css = " ".join(trial)
        if _css_count(root, css) == 1:
            chosen = trial
            break
    css = " ".join(chosen)
    cnt = _css_count(root, css)
    head = chosen[0] if chosen else ""
    if head.startswith("#"):
        score = 92
    elif head.startswith("["):
        score = 90
    elif "." in head:
        score = 64
    else:
        score = 52
    if len(chosen) > 2:
        score -= min((len(chosen) - 2) * 6, 24)
    score = max(0, min(100, score))
    return {"css": css, "count": cnt, "unique": cnt == 1, "score": score, "level": stability_label(score)}


def gen_playwright(el) -> list[dict[str, Any]]:
    attrs = {k: v for k, v in el.attrib.items() if not k.startswith("{")}
    out: list[dict[str, Any]] = []
    for a in ("data-testid", "data-test", "data-qa", "data-cy"):
        if attrs.get(a, "").strip():
            out.append({"code": f"getByTestId({_js(attrs[a])})", "label": f"@{a}", "score": 95})
            break
    role = attrs.get("role", "")
    name = attrs.get("aria-label", "") or _direct_text(el, 40)
    tag = _tag(el)
    if not role and tag in ("button", "a", "input", "select", "textarea"):
        role = {"button": "button", "a": "link", "input": "textbox", "select": "combobox", "textarea": "textbox"}[tag]
    if role and name:
        out.append({"code": f"getByRole({_js(role)}, {{ name: {_js(name)} }})", "label": "role + 名称", "score": 88})
    if attrs.get("aria-label", "").strip():
        out.append({"code": f"getByLabel({_js(attrs['aria-label'])})", "label": "@aria-label", "score": 80})
    if attrs.get("placeholder", "").strip():
        out.append({"code": f"getByPlaceholder({_js(attrs['placeholder'])})", "label": "@placeholder", "score": 75})
    txt = _direct_text(el, 40)
    if txt:
        out.append({"code": f"getByText({_js(txt)}, {{ exact: true }})", "label": "文本", "score": 68})
    return out


def _js(s: str) -> str:
    if "'" not in s:
        return "'" + s + "'"
    if '"' not in s:
        return '"' + s + '"'
    return "`" + s.replace("`", "\\`") + "`"


# --------------------------------------------------------------------------- #
# 表单标签锚定（label anchoring）
# 参考 cdnkr/xpath-generator 的「label/text anchoring」优先级：
# 当控件本身没有稳定属性时，用它的 <label> 文本作为锚点最耐用 ——
# 因为文案是产品/测试都在意的东西，重构时不容易被顺手改掉。
# --------------------------------------------------------------------------- #
def _all_text(el, limit: int = 120) -> str:
    try:
        return _norm(el.text_content())[:limit]
    except Exception:  # noqa: BLE001
        return _norm(el.text or "")[:limit]


def _label_text_for(el, root) -> str:
    """找出该控件对应的 <label> 文案（三种常见写法）。"""
    # 1) <label for="someId"> 显式关联
    eid = (el.attrib.get("id") or "").strip()
    if eid:
        for lb in (_xpath_of(root, f"//label[@for={_lit(eid)}]") or []):
            t = _norm(lb.text or "") or _all_text(lb, 60)
            if t:
                return t

    # 2) aria-labelledby 指向的节点
    ref = (el.attrib.get("aria-labelledby") or "").strip()
    if ref:
        for rid in ref.split()[:2]:
            for tgt in (_xpath_of(root, f"//*[@id={_lit(rid)}]") or []):
                t = _all_text(tgt, 60)
                if t:
                    return t

    # 3) <label> 直接包裹控件
    cur = el.getparent()
    while cur is not None:
        if _tag(cur) == "label":
            t = _norm(cur.text or "")
            if t:
                return t
            break
        cur = cur.getparent()
    return ""


def label_anchored_xpaths(el, root) -> list[tuple[str, dict]]:
    """生成以 <label> 文案为锚点的候选 XPath。

    只对表单类元素有意义；每条候选都带 tag 约束，避免 ``following-sibling::*[1]``
    这种会指向任意兄弟节点的危险写法。
    """
    tag = _tag(el)
    if tag not in ("input", "textarea", "select", "button", "a", "output"):
        return []
    txt = _label_text_for(el, root)
    if not txt or len(txt) > 60:
        return []
    lit = _lit(txt)
    meta = {"strategy": "label", "labelText": txt}
    return [
        (f"//label[normalize-space()={lit}]//{tag}", meta),
        (f"//label[normalize-space()={lit}]/following-sibling::{tag}[1]", meta),
        (f"//label[normalize-space()={lit}]/following::{tag}[1]", meta),
    ]


# --------------------------------------------------------------------------- #
# 候选生成总入口
# --------------------------------------------------------------------------- #
def ancestor_anchored_xpaths(el, root) -> list[tuple[str, dict]]:
    """用稳定祖先限定重复元素，跳过可能增删的中间包装层。

    独立实现祖先属性锚定思路；锚点和完整表达式均需命中正确元素。
    限制六层祖先、四条结果，避免页面扫描时无限组合。
    """
    tag = _tag(el)
    endings = []
    for pred, meta in _candidate_predicates(el):
        if meta["strategy"] not in ("testid", "id", "semantic", "text"):
            continue
        ending = f"{tag}[{pred}]"
        if not _locates_only(root, "//" + ending, el):
            endings.append((ending, min(76, _STRATEGY_BASE[meta["strategy"]])))
    if not _locates_only(root, "//" + tag, el):
        endings.append((tag, 70))
    if not endings:
        return []
    out = []
    seen = set()
    ancestor = el.getparent()
    for _ in range(6):
        if ancestor is None:
            break
        for pred, meta in _candidate_predicates(ancestor):
            if meta["strategy"] not in ("testid", "id", "semantic"):
                continue
            anchor = f"//{_tag(ancestor)}[{pred}]"
            if not _locates_only(root, anchor, ancestor):
                continue
            for ending, score_base in endings:
                xp = anchor + "//" + ending
                if xp not in seen and _locates_only(root, xp, el):
                    seen.add(xp)
                    out.append((xp, {"scoreBase": score_base, "anchor": _tag(ancestor)}))
                    if len(out) >= 4:
                        return out
        ancestor = ancestor.getparent()
    return out


def gen_for_element(root, el, index: dict[int, int]) -> dict[str, Any]:
    xpath_cands: list[dict[str, Any]] = []
    seen: set[str] = set()

    def push(xp: str, label: str, strategy: str, note: str = "", warn: str = "", score_base: int | None = None):
        xp = (xp or "").strip()
        if not xp or xp in seen:
            return
        seen.add(xp)
        res = _xpath_of(root, xp)
        n = len(res) if isinstance(res, list) else -1
        # 「唯一」必须同时满足：只匹配 1 个节点，且那个节点就是目标本身。
        # 只看数量会把「唯一但指错元素」的 XPath 误评为稳定。
        hit = bool(isinstance(res, list) and n == 1 and res[0] is el)
        score = _apply_penalty(_STRATEGY_BASE.get(strategy, 50) if score_base is None else score_base, xp, xp.count("/"))
        if not hit:
            score = min(score, 55)  # 非唯一 / 指错 / 无效：不应评为「稳定」
            if not warn and n == 1:
                warn = "唯一但指向了别的节点"
        xpath_cands.append(
            {
                "xpath": xp,
                "label": label,
                "strategy": strategy,
                "count": n,
                "unique": hit,
                "score": score,
                "level": stability_label(score),
                "note": note,
                "warn": warn,
            }
        )

    # 1) 最短唯一 XPath
    mini, depth, meta = minimal_xpath(el, root)
    push(mini, "最短唯一 XPath", meta.get("strategy", "path"), note=f"{depth} 级路径", warn=meta.get("warn", ""))

    # 2) 逐条策略候选（全局唯一性校验）
    tag = _tag(el)
    for pred, m in _candidate_predicates(el):
        push(f"//{tag}[{pred}]", _label_for(m), m.get("strategy", "attr"), warn=m.get("warn", ""))

    # 3) 表单标签锚定
    for xp, m in label_anchored_xpaths(el, root):
        push(xp, "标签锚定：" + m.get("labelText", ""), "label", note="表单控件缺稳定属性时最耐用")

    for xp, m in ancestor_anchored_xpaths(el, root):
        push(xp, "稳定祖先锚定", "ancestor", note="用祖先属性限定范围，跳过中间包装层", score_base=m["scoreBase"])

    # 4) 绝对路径兜底
    push(absolute_xpath(el), "绝对路径", "path", note="结构变化即失效，仅兜底")

    # 5) 列表模式
    lx = list_xpath(el, root)
    if lx:
        res = _xpath_of(root, lx)
        n = len(res) if isinstance(res, list) else 0
        if n > 1 and lx not in seen:
            seen.add(lx)
            xpath_cands.append(
                {
                    "xpath": lx,
                    "label": "列表模式（同类集合）",
                    "strategy": "list",
                    "count": n,
                    "unique": False,
                    "score": 66,
                    "level": "一般",
                    "note": f"匹配 {n} 个同类元素，适合批量提取",
                    "warn": "",
                }
            )

    xpath_cands.sort(key=lambda c: (not c["unique"], -c["score"], len(c["xpath"])))
    best = next((c["xpath"] for c in xpath_cands if c["unique"]), xpath_cands[0]["xpath"] if xpath_cands else "")

    return {
        "target": {
            "idx": index.get(id(el)),
            "tag": tag,
            "attrs": {k: v for k, v in el.attrib.items() if not k.startswith("{")},
            "text": _direct_text(el, 120),
            "dynamicId": is_dynamic_value(el.attrib.get("id", ""))[1] if el.attrib.get("id") else "",
        },
        "best": best,
        "xpath": xpath_cands,
        "css": gen_css(el, root),
        "playwright": gen_playwright(el),
    }


def _label_for(m: dict) -> str:
    st = m.get("strategy")
    if st == "testid":
        return f"测试属性 @{m.get('attr')}"
    if st == "id":
        return "id 定位"
    if st == "semantic":
        return f"语义属性 @{m.get('attr')}"
    if st == "text":
        return "精确文本"
    if st == "class":
        return f"class={m.get('cls')}"
    if st == "combo":
        return "多属性组合"
    return "属性定位"


# --------------------------------------------------------------------------- #
# 自然语言检索（离线）
# --------------------------------------------------------------------------- #
_STOP = set("的 了 个 是 我 要 在 页面 中 里 上 下 和 与 或 请 帮 找 选 取 元素 the a an of to in on for and or please find select element".split())


def _tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9_\-]+|[\u4e00-\u9fff]+", (text or "").lower())
    return [t for t in toks if t not in _STOP]


def nl_search(root, index: dict[int, int], query: str, limit: int = 40) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"count": 0, "matches": []}
    toks = _tokens(q)
    ql = q.lower()
    hints = {
        "按钮": ("button", lambda t, a, b: t == "button" or a.get("type") == "button" or "btn" in b),
        "button": ("button", lambda t, a, b: t == "button" or "btn" in b),
        "链接": ("链接", lambda t, a, b: t == "a" or "href" in a),
        "link": ("链接", lambda t, a, b: t == "a" or "href" in a),
        "输入": ("输入框", lambda t, a, b: t in ("input", "textarea", "select")),
        "input": ("输入框", lambda t, a, b: t in ("input", "textarea")),
        "图片": ("图片", lambda t, a, b: t in ("img", "svg", "picture")),
        "image": ("图片", lambda t, a, b: t in ("img", "svg")),
        "表格": ("表格", lambda t, a, b: t in ("table", "tr", "td", "th")),
        "表单": ("表单", lambda t, a, b: t == "form"),
        "标题": ("标题", lambda t, a, b: t in ("h1", "h2", "h3", "h4", "h5", "h6")),
    }

    scored = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        blob = " ".join([tag] + [f"{k}={v}" for k, v in el.attrib.items()] + [_direct_text(el, 80)]).lower()
        score = 0.0
        reasons = []
        if tag in ql:
            score += 3
            reasons.append(f"标签 {tag}")
        for t in toks:
            if t in blob:
                score += 2 if t in tag else 1
                if any("\u4e00" <= ch <= "\u9fff" for ch in t):
                    score += 2
        for key, (label, fn) in hints.items():
            if key in ql and fn(tag, el.attrib, blob):
                score += 3
                reasons.append(label)
        if score > 0:
            scored.append((score, el, "、".join(dict.fromkeys(reasons))))

    scored.sort(key=lambda x: -x[0])
    matches = [
        {"idx": index.get(id(el)), "tag": _tag(el), "attrs": dict(el.attrib), "text": _direct_text(el, 120),
         "score": round(sc, 2), "reason": rs}
        for sc, el, rs in scored[:limit]
    ]
    return {"count": len(matches), "matches": matches}


# --------------------------------------------------------------------------- #
# 页面扫描：找出所有可交互元素的最佳定位器
# --------------------------------------------------------------------------- #
_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "option", "label", "summary"}
_INTERACTIVE_ROLES = {"button", "link", "checkbox", "radio", "tab", "menuitem", "textbox", "combobox", "switch", "option"}


def scan_page(root, index: dict[int, int], limit: int = 400) -> dict[str, Any]:
    out = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        role = el.attrib.get("role", "")
        interactive = (
            tag in _INTERACTIVE_TAGS
            or role in _INTERACTIVE_ROLES
            or "onclick" in el.attrib
            or "data-testid" in el.attrib
            or "contenteditable" in el.attrib
        )
        if not interactive:
            continue
        if tag == "input" and el.attrib.get("type") == "hidden":
            continue
        xp, depth, meta = minimal_xpath(el, root)
        score = _apply_penalty(_STRATEGY_BASE.get(meta.get("strategy", "path"), 50), xp, depth)
        out.append(
            {
                "idx": index.get(id(el)),
                "tag": _tag(el),
                "text": _direct_text(el, 60),
                "attrs": {k: v for k, v in el.attrib.items() if k not in ("class",)},
                "xpath": xp,
                "score": score,
                "level": stability_label(score),
            }
        )
        if len(out) >= limit:
            break
    out.sort(key=lambda x: -x["score"])
    return {"count": len(out), "items": out}


# --------------------------------------------------------------------------- #
# 批量验证
# --------------------------------------------------------------------------- #
def _looks_like_css(sel: str) -> bool:
    s = sel.strip()
    if not s:
        return False
    if s.startswith(("/", "(", "//")):
        return False
    if s.startswith("getBy"):
        return False
    return True


# --------------------------------------------------------------------------- #
# 定位器自愈建议（Healenium 式）
#
# 页面改版后老 XPath 会失配（count == 0）。这里从**选择器字符串本身**反推出
# 当初想找什么（标签 / 属性值 / class / 文案），再在现在的 DOM 里按相似度找
# 最像的那个元素，给出一条可用的替代 XPath。
#
# 相似度维度与权重参考 Healenium 的 Scored<Node>，阈值取它默认的 0.6：
#     标签 0.25 | 属性 0.35 | class 0.20 | 文案 0.20
# --------------------------------------------------------------------------- #
HEAL_THRESHOLD = 0.6


def _round3(x: float) -> float:
    """与 JS 的 ``Math.round(x*1000)/1000`` 完全一致（Python 的 round 是银行家舍入，会差一位）。"""
    return math.floor(x * 1000 + 0.5) / 1000

_HINT_TAG = re.compile(r"^\(?\s*/{1,2}([a-zA-Z][\w-]*)")
_HINT_ATTR = re.compile(r"@([\w:.-]+)\s*=\s*(?:'([^']*)'|\"([^\"]*)\")")
_HINT_TEXT = re.compile(r"(?:normalize-space\(\s*text\(\)\s*\)|text\(\))\s*=\s*(?:'([^']*)'|\"([^\"]*)\")")


def _tokens_of(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _bigrams(s: str) -> set[str]:
    s = (s or "").lower()
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _similar_text(a: str, b: str) -> float:
    """两个字符串的相似度 0~1（Sørensen–Dice 二元组 + token Jaccard + 包含加成）。

    ``login-btn`` vs ``login-button`` → ~0.63（同一个按钮改了命名）
    ``login-btn`` vs ``register-btn`` → ~0.42（不相干）
    """
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    ba, bb = _bigrams(a), _bigrams(b)
    dice = (2 * len(ba & bb) / (len(ba) + len(bb))) if (ba or bb) else 0.0

    ta, tb = _tokens_of(a), _tokens_of(b)
    jac = (len(ta & tb) / len(ta | tb)) if (ta and tb) else 0.0

    base = max(dice, jac)
    if a in b or b in a:
        base = min(1.0, base + 0.15)
    return base


def _extract_contains_class(sel: str) -> list[str]:
    """抓出 ``contains(..., ' X ')`` 里的 class token。

    引擎生成的是 ``contains(concat(' ', normalize-space(@class), ' '), ' X ')``，
    里面有嵌套括号，所以必须做括号配对，不能简单用正则的 ``[^)]*``。
    """
    out: list[str] = []
    i = 0
    while True:
        i = sel.find("contains(", i)
        if i < 0:
            break
        start = i + len("contains(")
        depth = 1
        j = start
        while j < len(sel) and depth:
            if sel[j] == "(":
                depth += 1
            elif sel[j] == ")":
                depth -= 1
            j += 1
        inner = sel[start:j - 1]
        i = j
        if "@class" not in inner:
            continue
        lits = re.findall(r"'([^']*)'", inner)
        if lits:
            tok = lits[-1].strip()
            if tok:
                out.append(tok)
    return out


def parse_selector_hints(selector: str) -> dict[str, Any]:
    """从一条 XPath 里抽出「当初想找什么」。"""
    sel = selector or ""
    tag = ""
    m = _HINT_TAG.match(sel.strip())
    if m:
        tag = m.group(1).lower()

    # 用 list 而不是 tuple：这些结构会直接进 JSON 响应
    attrs: list[list[str]] = []
    for am in _HINT_ATTR.finditer(sel):
        v = am.group(2) if am.group(2) is not None else am.group(3)
        attrs.append([am.group(1), v or ""])

    classes = _extract_contains_class(sel)

    text = ""
    tm = _HINT_TEXT.search(sel)
    if tm:
        text = tm.group(1) if tm.group(1) is not None else (tm.group(2) or "")

    return {"tag": tag, "attrs": attrs, "classes": classes, "text": text}


def _class_similarity(want: list[str], el_classes: list[str]) -> tuple[float, str]:
    """class 维度相似度。

    BEM 风格的类名里「第一个词」通常是块名（cart-link / cart-entry 都是 cart 块），
    首词相同要额外加分，否则 ``cart-link`` → ``cart-entry`` 这种改名会被低估。
    """
    want_tokens: set[str] = set()
    for c in want:
        want_tokens |= _tokens_of(c)
    if not want_tokens:
        return 0.0, ""
    # 注意：两边都要 token 化后再比，否则 "cart-entry" 会被当成一个整体 token
    el_tokens: set[str] = set()
    for c in el_classes:
        el_tokens |= _tokens_of(c)

    overlap = len(want_tokens & el_tokens) / len(want_tokens)

    want_str = " ".join(want).lower()
    el_str = " ".join(el_classes).lower()
    best = max(overlap, _similar_text(want_str, el_str))

    if want_tokens & el_tokens:
        best = min(1.0, best + 0.15)

    hit = want_tokens & el_tokens
    reason = ("class 命中：" + ", ".join(sorted(hit)[:3])) if hit else ""
    return best, reason


def _heal_score(el, hints: dict[str, Any]) -> tuple[float, list[str]]:
    """给候选元素打分（0~1）+ 中文理由。

    只在「有提示的维度」上加权再归一化 —— 否则一条只写了 class 的选择器
    会因为拿不到 tag/文案分而被系统性压低。
    """
    reasons: list[str] = []
    tag = hints["tag"]
    el_tag = _tag(el).lower()

    if tag and el_tag != tag:
        return 0.0, []
    if tag:
        reasons.append(f"标签仍为 <{tag}>")

    el_attrs = {k: v for k, v in el.attrib.items() if not k.startswith("{")}
    dims: list[tuple[float, float]] = []

    if tag:
        dims.append((0.25, 1.0))

    # 属性维度
    if hints["attrs"]:
        best = 0.0
        for name, val in hints["attrs"]:
            cur = el_attrs.get(name)
            if cur is not None:
                sim = _similar_text(val, cur)
                if sim >= 0.999:
                    reasons.append(f"@{name} 值未变")
                elif sim >= 0.6:
                    reasons.append(f"@{name} 值近似：{cur}")
                best = max(best, sim)
                continue
            for k2, v2 in el_attrs.items():
                sim = _similar_text(val, v2)
                if sim >= 0.7:
                    best = max(best, sim * 0.85)
                    reasons.append(f"原 @{name} 的值搬到了 @{k2}")
                    break
        dims.append((0.35, best))

    # class 维度
    if hints["classes"]:
        cs, cr = _class_similarity(hints["classes"], stable_class_tokens(el_attrs.get("class", "")))
        if cr:
            reasons.append(cr)
        dims.append((0.20, cs))

    # 文案维度
    if hints["text"]:
        sim = _similar_text(hints["text"], _direct_text(el, 80))
        if sim >= 0.6:
            reasons.append("文案接近")
        dims.append((0.20, sim))

    if not dims:
        return 0.0, []
    total_w = sum(w for w, _ in dims)
    return min(1.0, sum(w * s for w, s in dims) / total_w), reasons


def _heal_from_hints(root, index: dict[int, int], hints: dict[str, Any],
                     limit: int = 3, max_pool: int = 4000) -> list[dict[str, Any]]:
    if not (hints.get("tag") or hints.get("attrs") or hints.get("classes") or hints.get("text")):
        return []

    pool_xp = f"//{hints['tag']}" if hints.get("tag") else "//*"
    pool = _xpath_of(root, pool_xp) or []
    if not isinstance(pool, list):
        return []
    if len(pool) > max_pool:
        pool = pool[:max_pool]

    scored: list[tuple[float, Any, list[str]]] = []
    for el in pool:
        if not isinstance(el, etree._Element):
            continue
        sc, reasons = _heal_score(el, hints)
        if sc >= HEAL_THRESHOLD:
            scored.append((sc, el, reasons))

    scored.sort(key=lambda x: -x[0])
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sc, el, reasons in scored:
        xp = minimal_xpath(el, root)[0]
        if not xp or xp in seen:
            continue
        seen.add(xp)
        out.append({
            "xpath": xp,
            "score": _round3(sc),
            "idx": index.get(id(el)),
            "tag": _tag(el),
            "text": _direct_text(el, 60),
            "reason": "、".join(dict.fromkeys(reasons)),
            "confidence": "高" if sc >= 0.8 else ("中" if sc >= 0.7 else "低"),
        })
        if len(out) >= limit:
            break
    return out


def heal_selector(root, index: dict[int, int], selector: str, limit: int = 3) -> list[dict[str, Any]]:
    """给一条失配的 XPath 找替代方案，按相似度降序返回。"""
    return _heal_from_hints(root, index, parse_selector_hints(selector), limit)


def parse_css_hints(selector: str) -> dict[str, Any]:
    """把 CSS 选择器粗略翻成同一套 hints。"""
    sel = (selector or "").strip()
    hints: dict[str, Any] = {"tag": "", "attrs": [], "classes": [], "text": ""}
    m = re.match(r"^([a-zA-Z][\w-]*)", sel)
    if m:
        hints["tag"] = m.group(1).lower()
    hints["classes"] = [c for c in re.findall(r"\.([\w-]+)", sel)]
    for am in re.finditer(r"\[([\w-]+)\s*=\s*['\"]?([^'\"]*)['\"]?\]", sel):
        hints["attrs"].append([am.group(1), am.group(2)])
    im = re.search(r"#([\w-]+)", sel)
    if im:
        hints["attrs"].append(["id", im.group(1)])
    return hints


def heal_css_selector(root, index: dict[int, int], selector: str, limit: int = 3) -> list[dict[str, Any]]:
    return _heal_from_hints(root, index, parse_css_hints(selector), limit)


def verify_batch(root, index: dict[int, int], selectors: list[str]) -> dict[str, Any]:
    results = []
    for raw in selectors:
        sel = (raw or "").strip()
        if not sel:
            continue
        item = {"selector": sel, "type": "", "valid": False, "count": 0, "error": "", "idx": None,
                "note": "", "heal": []}
        if sel.startswith("getBy"):
            item["type"] = "playwright"
            item["note"] = "Playwright 定位器需在浏览器中运行验证"
            results.append(item)
            continue
        if _looks_like_css(sel):
            item["type"] = "css"
            cnt = _css_count(root, sel)
            if cnt is None:
                item["error"] = "CSS 解析失败或未安装 cssselect"
            else:
                item["valid"] = True
                item["count"] = cnt
            if item["valid"] and cnt == 0:
                item["heal"] = heal_css_selector(root, index, sel)
            results.append(item)
            continue
        item["type"] = "xpath"
        res = _xpath_of(root, sel)
        if res is None:
            item["error"] = "XPath 表达式无效"
        else:
            item["valid"] = True
            item["count"] = len(res) if isinstance(res, list) else 1
            if res and isinstance(res[0], etree._Element):
                item["idx"] = index.get(id(res[0]))
        # 失配才给自愈建议（命中数 > 0 说明还能用）
        if item["valid"] and item["count"] == 0:
            item["heal"] = heal_selector(root, index, sel)
        results.append(item)
    return {"count": len(results), "results": results}


# --------------------------------------------------------------------------- #
# 便捷封装
# --------------------------------------------------------------------------- #
def load(source: str):
    """解析并构建索引，返回 (root, index, tree, count, elements)。

    elements 必须由调用方持有强引用，否则 id() 映射会失效。
    """
    root = parse_html(source)
    tree, index, count, elements = build_tree(root)
    return root, index, tree, count, elements
