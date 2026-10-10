/* ============================================================
 * XPath Studio · 浏览器定位引擎
 * ------------------------------------------------------------
 * Python 版 xpath_engine.py 的浏览器移植，基于原生 document.evaluate
 * （真正的 XPath 1.0 引擎，与 lxml 语义一致）。
 *
 * 算法思路参考：
 *   - Robula+           最短唯一 XPath（从绝对路径逐步削减前缀步骤）
 *   - xpath-helper-plus class token 匹配 / 剔除运行时状态 class / 位置索引语义
 *   - XPath Forte       稳定性评分模型 / 动态 ID 识别 / 多类型定位器
 * ============================================================ */
(function (global) {
  "use strict";

  var UI_ROOT_ID = "__xpath_studio_root__";

  /* ------------------------------------------------------------------ *
   * 常量
   * ------------------------------------------------------------------ */
  var DYNAMIC_PATTERNS = [
    [/^j_idt?\d/i, "JSF 动态 ID"],
    [/^j_id/i, "JSF 动态 ID"],
    [/^ng-/i, "Angular 生成"],
    [/^_ngcontent/i, "Angular 视图封装"],
    [/^_nghost/i, "Angular 视图封装"],
    [/^data-v-/i, "Vue scoped 标记"],
    [/^sc-[A-Za-z0-9]{4,}/i, "styled-components 哈希"],
    [/^css-[a-z0-9]{4,}/i, "emotion 哈希"],
    [/^mui-\d/i, "Material-UI 生成"],
    [/^svelte-/i, "Svelte scoped 哈希"],
    [/^ember\d/i, "Ember 生成"],
    [/^radix-/i, "Radix 生成"],
    [/^headlessui-/i, "HeadlessUI 生成"],
    [/^react-select-\d/i, "react-select 生成"],
    // React 18 useId：id 形如 ":r1a:" / ":R2b:"
    [/^:r[0-9a-z]+:$/i, "React useId"],
    // 纯数字 / 列表项自增 id
    [/^\d+$/, "纯数字"],
    [/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i, "UUID"],
    [/^[0-9a-f]{16,}$/i, "十六进制哈希"]
  ];

  var UNSTABLE_CLASSES = new Set(
    ("active hover focus focused focus-visible selected checked open opened closed close " +
      "show shown hide hidden visible invisible disabled enabled current loading loaded " +
      "collapsed expanded dragging dragover animating animate on off error success " +
      "warning invalid valid dirty is-active is-open is-selected is-hidden is-visible " +
      "is-collapsed is-expanded is-loading is-disabled is-error is-success has-error " +
      "has-success sr-only visually-hidden").split(" ")
  );

  // Tailwind 的「状态变体」前缀（hover:bg-red-600 之类）：只影响观感，做定位器没意义。
  // 响应式/暗色变体（sm: / md: / dark:）反而描述布局，保留。
  var TAILWIND_STATE_VARIANT =
    /^(hover|focus|focus-within|focus-visible|active|visited|target|disabled|checked|indeterminate|default|required|valid|invalid|placeholder-shown|autofill|read-only|group-hover|group-focus|group-active|group-disabled|peer-hover|peer-focus|peer-checked|before|after|first|last|odd|even):/i;

  var STRATEGY_BASE = {
    testid: 95,
    id: 88,
    semantic: 78,
    label: 74,
    ancestor: 76,
    combo: 72,
    text: 70,
    attr: 66,
    class: 60,
    list: 66,
    index: 40,
    id_dynamic: 42,
    path: 22
  };

  // 这些属性是**专门为测试/自动化准备的**，即使长得像哈希也应当被信任。
  var TESTID_ATTRS = [
    "data-testid", "data-test", "data-test-id", "data-qa", "data-cy", "data-automation-id"
  ];

  /* ------------------------------------------------------------------ *
   * 基础工具
   * ------------------------------------------------------------------ */
  function tagOf(el) {
    return el && el.tagName ? String(el.tagName).toLowerCase() : "";
  }

  function attrsOf(el) {
    var out = {};
    if (!el || !el.attributes) return out;
    for (var i = 0; i < el.attributes.length; i++) {
      var a = el.attributes[i];
      if (!a || !a.name) continue;
      if (a.name.indexOf("xmlns") === 0) continue;
      out[a.name] = a.value;
    }
    return out;
  }

  function normalizeWs(s) {
    return String(s == null ? "" : s).replace(/\s+/g, " ").trim();
  }

  function directText(el, limit) {
    if (!el || !el.childNodes) return "";
    var buf = "";
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3) buf += n.nodeValue;
    }
    return normalizeWs(buf).slice(0, limit || 80);
  }

  function fullText(el, limit) {
    return normalizeWs(el && el.textContent).slice(0, limit || 120);
  }

  function elementChildren(el) {
    var out = [];
    if (!el || !el.children) return out;
    for (var i = 0; i < el.children.length; i++) out.push(el.children[i]);
    return out;
  }

  /** 判断节点是否属于本扩展注入的 UI，需从匹配结果中排除 */
  function isOurNode(node) {
    if (!node) return false;
    var el = node.nodeType === 1 ? node : node.parentElement;
    if (!el) return false;
    if (el.id === UI_ROOT_ID) return true;
    if (!el.closest) return false;
    if (el.closest("#" + UI_ROOT_ID)) return true;
    if (el.closest("[data-xps]")) return true;
    return false;
  }

  /** XPath 字符串字面量（处理引号冲突） */
  function xpathLiteral(s) {
    s = String(s);
    if (s.indexOf("'") === -1) return "'" + s + "'";
    if (s.indexOf('"') === -1) return '"' + s + '"';
    var parts = s.split("'");
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      if (i > 0) out.push("\"'\"");
      if (parts[i]) out.push("'" + parts[i] + "'");
    }
    return "concat(" + out.join(", ") + ")";
  }

  /* ------------------------------------------------------------------ *
   * 动态值 / 稳定性
   * ------------------------------------------------------------------ */
  function isDynamicValue(value) {
    var v = normalizeWs(value);
    if (!v) return [true, "空值"];
    for (var i = 0; i < DYNAMIC_PATTERNS.length; i++) {
      if (DYNAMIC_PATTERNS[i][0].test(v)) return [true, DYNAMIC_PATTERNS[i][1]];
    }
    if (v.length >= 8) {
      var digits = 0;
      for (var j = 0; j < v.length; j++) if (v[j] >= "0" && v[j] <= "9") digits++;
      var ratio = digits / v.length;
      if (ratio > 0.6) return [true, "数字占比过高"];
      if (/\d{5,}$/.test(v) && ratio > 0.4) return [true, "以长数字结尾"];
    }
    return [false, ""];
  }

  // 判断 class token 是否像构建工具生成的哈希。
  // 两类（都要求「大小写/数字混杂」，避免误杀 Tailwind 的 bg-red-500、
  // text-2xl、space-y-4 这类稳定工具类）：
  //   1) 裸哈希：dKpMkN、x7hF2
  //   2) 前缀 + 哈希：sc-bdVaJa、css-1q2w3e、svelte-1a2b3c
  function isHashyToken(t) {
    if (!t) return false;
    var up = 0, lo = 0, di = 0, i, c;
    function count(s) {
      up = 0; lo = 0; di = 0;
      for (var j = 0; j < s.length; j++) {
        c = s[j];
        if (c >= "A" && c <= "Z") up++;
        else if (c >= "a" && c <= "z") lo++;
        else if (c >= "0" && c <= "9") di++;
      }
    }

    if (/^[A-Za-z0-9]{5,10}$/.test(t)) {
      if (/^[a-z]+$/.test(t)) return false;   // 全小写普通单词
      count(t);
      return (up >= 2 && lo >= 2) || (up >= 1 && di >= 1) || (lo >= 2 && di >= 2);
    }

    var m = /^[A-Za-z_]\w*-([A-Za-z0-9]{4,})$/.exec(t);
    if (!m) return false;
    count(m[1]);
    return (up >= 2 && lo >= 2) || (lo >= 2 && di >= 2) || (up >= 1 && lo >= 1 && di >= 1);
  }

  function stableClassTokens(classStr) {
    var toks = normalizeWs(classStr).split(" ").filter(Boolean);
    var good = [];
    for (var i = 0; i < toks.length; i++) {
      var t = toks[i];
      if (UNSTABLE_CLASSES.has(t.toLowerCase())) continue;
      if (t.indexOf("js-") === 0 || t.indexOf("css-") === 0) continue;
      if (TAILWIND_STATE_VARIANT.test(t)) continue;
      var dyn = isDynamicValue(t)[0];
      if (dyn && /^[A-Za-z0-9_-]{8,}$/.test(t) && !/^[a-z]+(-[a-z]+)+$/.test(t)) continue;
      // CSS-in-JS / scoped 哈希（dKpMkN、sc-bdVaJa、css-1q2w3e…）
      if (isHashyToken(t)) continue;
      good.push(t);
    }
    good.sort(function (a, b) { return b.length - a.length || (a < b ? -1 : 1); });
    return good;
  }

  function stabilityLabel(score) {
    if (score >= 70) return "稳定";
    if (score >= 45) return "一般";
    return "脆弱";
  }

  function applyPenalty(score, xp, depth) {
    if (/^\(?\s*\/html\b/.test(xp)) score = Math.min(score, 20);
    else if (/^\/\/(body|html)\b/.test(xp)) score = Math.min(score, 35);
    if (/\[\d+\]/.test(xp)) score = Math.min(score, 40);
    if (xp.indexOf("sibling::") !== -1) score = Math.min(score, 50);
    if (depth > 4) score -= Math.min((depth - 4) * 5, 20);
    if (xp.indexOf("contains(text()") !== -1 || xp.indexOf("contains(.,") !== -1) score -= 6;
    return Math.max(0, Math.min(100, score));
  }

  /* ------------------------------------------------------------------ *
   * XPath 求值
   * ------------------------------------------------------------------ */
  function evalNodes(xpath, context) {
    try {
      var ctx = context || document;
      var doc = ctx.ownerDocument || ctx;
      var res = doc.evaluate(xpath, ctx, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      var out = [];
      for (var i = 0; i < res.snapshotLength; i++) out.push(res.snapshotItem(i));
      return out;
    } catch (e) {
      return null;
    }
  }

  function visibleNodes(nodes) {
    if (!nodes) return [];
    return nodes.filter(function (n) { return !isOurNode(n); });
  }

  function locatesOnly(xpath, el) {
    var nodes = visibleNodes(evalNodes(xpath));
    return nodes.length === 1 && nodes[0] === el;
  }

  function cleanError(e) {
    var m = String((e && e.message) || e || "");
    m = m.split("\n")[0];
    return m.replace(/^Failed to execute 'evaluate' on 'Document':\s*/i, "");
  }

  function validate(xpath) {
    var xp = String(xpath == null ? "" : xpath).trim();
    if (!xp) return { valid: false, error: "XPath 不能为空", count: 0, matches: [] };
    var res;
    try {
      res = document.evaluate(xp, document, null, XPathResult.ANY_TYPE, null);
    } catch (e) {
      return { valid: false, error: cleanError(e), count: 0, matches: [] };
    }
    var T = XPathResult;
    if (res.resultType === T.NUMBER_TYPE) {
      return { valid: true, count: 1, matches: [{ kind: "value", value: String(res.numberValue) }] };
    }
    if (res.resultType === T.STRING_TYPE) {
      return { valid: true, count: 1, matches: [{ kind: "value", value: res.stringValue }] };
    }
    if (res.resultType === T.BOOLEAN_TYPE) {
      return { valid: true, count: 1, matches: [{ kind: "value", value: String(res.booleanValue) }] };
    }
    var nodes = [];
    var n;
    while ((n = res.iterateNext())) nodes.push(n);
    var visible = nodes.filter(function (x) { return !isOurNode(x); });
    var matches = visible.slice(0, 500).map(function (x) {
      if (x.nodeType === 1) {
        return { kind: "node", node: x, tag: tagOf(x), attrs: attrsOf(x), text: fullText(x, 120) };
      }
      return { kind: "value", value: String(x.nodeValue || x) };
    });
    return {
      valid: true,
      count: visible.length,
      matches: matches,
      truncated: visible.length > 500
    };
  }

  /* ------------------------------------------------------------------ *
   * 谓词生成
   * ------------------------------------------------------------------ */
  function candidatePredicates(el) {
    var out = [];
    var attrs = attrsOf(el);

    // 1) 测试专用属性（最稳健）。
    //    注意：这里**不做动态值判定** —— 这些属性就是给自动化用的，
    //    即便值看起来像哈希（如 data-testid="a1b2c3d4e5f6"）也应当信任。
    for (var i = 0; i < TESTID_ATTRS.length; i++) {
      var a = TESTID_ATTRS[i];
      var v = normalizeWs(attrs[a]);
      if (v) {
        out.push(["@" + a + "=" + xpathLiteral(v), { strategy: "testid", attr: a }]);
      }
    }

    // 2) id
    if (normalizeWs(attrs.id)) {
      var idv = attrs.id;
      var dyn = isDynamicValue(idv);
      if (dyn[0]) {
        out.push(["@id=" + xpathLiteral(idv), { strategy: "id_dynamic", attr: "id", warn: "疑似动态 ID（" + dyn[1] + "）" }]);
      } else {
        out.push(["@id=" + xpathLiteral(idv), { strategy: "id", attr: "id" }]);
      }
    }

    // 3) 语义属性
    var semanticAttrs = ["name", "aria-label", "role", "placeholder", "alt", "title", "type", "value", "href"];
    for (var j = 0; j < semanticAttrs.length; j++) {
      var sa = semanticAttrs[j];
      var sv = normalizeWs(attrs[sa]);
      if (!sv || sv.length > 120) continue;
      if (isDynamicValue(sv)[0] && sa !== "type" && sa !== "href" && sa !== "role") continue;
      var strat = (sa === "name" || sa === "aria-label" || sa === "role") ? "semantic" : "attr";
      out.push(["@" + sa + "=" + xpathLiteral(sv), { strategy: strat, attr: sa }]);
    }

    // 4) 其它 data-* 属性
    for (var name in attrs) {
      if (!Object.prototype.hasOwnProperty.call(attrs, name)) continue;
      if (name.indexOf("data-") !== 0) continue;
      if (TESTID_ATTRS.indexOf(name) !== -1) continue;
      var dv = normalizeWs(attrs[name]);
      if (dv && dv.length <= 120 && !isDynamicValue(dv)[0]) {
        out.push(["@" + name + "=" + xpathLiteral(dv), { strategy: "attr", attr: name }]);
      }
    }

    // 5) 精确文本
    var txt = directText(el, 50);
    if (txt) {
      out.push(["normalize-space(text())=" + xpathLiteral(txt), { strategy: "text" }]);
    }

    // 6) class token
    var classes = stableClassTokens(attrs["class"] || "");
    for (var c = 0; c < Math.min(classes.length, 4); c++) {
      var cls = classes[c];
      out.push([
        "contains(concat(' ', normalize-space(@class), ' '), " + xpathLiteral(" " + cls + " ") + ")",
        { strategy: "class", cls: cls }
      ]);
    }

    // 7) 多属性组合
    var comboAttrs = ["name", "type", "role", "aria-label"].filter(function (k) { return normalizeWs(attrs[k]); });
    if (comboAttrs.length >= 2) {
      var combo = comboAttrs.slice(0, 2).map(function (k) {
        return "@" + k + "=" + xpathLiteral(attrs[k]);
      }).join(" and ");
      out.push([combo, { strategy: "combo" }]);
    }

    return out;
  }

  function stepFor(el, parent) {
    var tag = tagOf(el);
    var preds = candidatePredicates(el);
    for (var i = 0; i < preds.length; i++) {
      var pred = preds[i][0], meta = preds[i][1];
      var nodes = evalNodes("./" + tag + "[" + pred + "]", parent);
      if (nodes && nodes.length === 1 && nodes[0] === el) {
        return [tag + "[" + pred + "]", meta];
      }
    }
    var sibs = elementChildren(parent).filter(function (c) { return tagOf(c) === tag; });
    var idx = sibs.indexOf(el) + 1;
    return [tag + "[" + (idx > 0 ? idx : 1) + "]", { strategy: "index" }];
  }

  function chainOf(el) {
    var out = [];
    var cur = el;
    while (cur) {
      out.push(cur);
      cur = cur.parentElement;
    }
    out.reverse();
    return out;
  }

  /** Robula+ 式最短唯一 XPath */
  function minimalXPath(el) {
    var chain = chainOf(el);
    if (chain.length <= 1) return ["/" + tagOf(el), 1, { strategy: "path" }];
    var steps = [];
    var meta = { strategy: "path" };
    for (var i = 1; i < chain.length; i++) {
      var r = stepFor(chain[i], chain[i - 1]);
      steps.push(r[0]);
      if (chain[i] === el) meta = r[1];
    }
    var chosen = steps;
    for (var k = steps.length - 1; k >= 0; k--) {
      var trial = steps.slice(k);
      var xp = "//" + trial.join("/");
      if (locatesOnly(xp, el)) { chosen = trial; break; }
    }
    return ["//" + chosen.join("/"), chosen.length, meta];
  }

  function absoluteXPath(el) {
    var chain = chainOf(el);
    var parts = [];
    for (var i = 0; i < chain.length; i++) {
      var node = chain[i];
      var parent = node.parentElement;
      var tag = tagOf(node);
      if (!parent) { parts.push(tag); continue; }
      var sibs = elementChildren(parent).filter(function (c) { return tagOf(c) === tag; });
      parts.push(sibs.length > 1 ? tag + "[" + (sibs.indexOf(node) + 1) + "]" : tag);
    }
    return "/" + parts.join("/");
  }

  /** 列表模式：优先挑能匹配到多个同类元素的谓词 */
  function listXPath(el) {
    var tag = tagOf(el);
    var best = null;
    var preds = candidatePredicates(el);
    for (var i = 0; i < preds.length; i++) {
      var xp = "//" + tag + "[" + preds[i][0] + "]";
      var nodes = visibleNodes(evalNodes(xp));
      if (nodes.length > 1) {
        var score = STRATEGY_BASE[preds[i][1].strategy] || 50;
        if (!best || score > best[0]) best = [score, xp, nodes.length];
      }
    }
    if (best) return best[1];
    var chain = chainOf(el);
    if (chain.length <= 1) return "//" + tag;
    var steps = [];
    for (var k = 1; k < chain.length; k++) {
      var r = stepFor(chain[k], chain[k - 1]);
      var s = r[0];
      if (chain[k] === el && r[1].strategy === "index") s = tagOf(chain[k]);
      steps.push(s);
    }
    var full = "//" + steps.join("/");
    if (evalNodes(full)) return full;
    return steps.length > 1 ? "//" + steps.slice(0, -1).join("/") : full;
  }

  /* ------------------------------------------------------------------ *
   * CSS / Playwright
   * ------------------------------------------------------------------ */
  function cssEscapeIdent(s) {
    if (global.CSS && typeof global.CSS.escape === "function") return global.CSS.escape(s);
    return String(s).replace(/([^\w-])/g, "\\$1");
  }

  function cssStep(el) {
    var attrs = attrsOf(el);
    if (normalizeWs(attrs.id) && !isDynamicValue(attrs.id)[0]) {
      return "#" + cssEscapeIdent(attrs.id);
    }
    for (var i = 0; i < TESTID_ATTRS.length; i++) {
      var a = TESTID_ATTRS[i];
      if (normalizeWs(attrs[a])) return '[' + a + '="' + String(attrs[a]).replace(/"/g, '\\"') + '"]';
    }
    var tag = tagOf(el);
    var cls = stableClassTokens(attrs["class"] || "").slice(0, 2);
    if (cls.length) return tag + cls.map(function (c) { return "." + cssEscapeIdent(c); }).join("");
    var order = ["name", "aria-label", "placeholder", "type"];
    for (var j = 0; j < order.length; j++) {
      if (normalizeWs(attrs[order[j]])) {
        return tag + "[" + order[j] + '="' + String(attrs[order[j]]).replace(/"/g, '\\"') + '"]';
      }
    }
    return tag;
  }

  function cssCount(css) {
    try {
      var nodes = document.querySelectorAll(css);
      var cnt = 0;
      for (var i = 0; i < nodes.length; i++) if (!isOurNode(nodes[i])) cnt++;
      return cnt;
    } catch (e) {
      return null;
    }
  }

  function genCss(el) {
    var chain = chainOf(el).slice(1);
    if (!chain.length) {
      return { css: tagOf(el), count: 1, unique: true, score: 30, level: "脆弱" };
    }
    var parts = chain.map(cssStep);
    var chosen = parts;
    for (var i = parts.length - 1; i >= 0; i--) {
      var trial = parts.slice(i);
      var css = trial.join(" ");
      if (cssCount(css) === 1) { chosen = trial; break; }
    }
    var result = chosen.join(" ");
    var cnt = cssCount(result);
    var head = chosen[0] || "";
    var score;
    if (head.charAt(0) === "#") score = 92;
    else if (head.charAt(0) === "[") score = 90;
    else if (head.indexOf(".") !== -1) score = 64;
    else score = 52;
    if (chosen.length > 2) score -= Math.min((chosen.length - 2) * 6, 24);
    score = Math.max(0, Math.min(100, score));
    return { css: result, count: cnt, unique: cnt === 1, score: score, level: stabilityLabel(score) };
  }

  function jsLiteral(s) {
    s = String(s);
    if (s.indexOf("'") === -1) return "'" + s + "'";
    if (s.indexOf('"') === -1) return '"' + s + '"';
    return "`" + s.replace(/`/g, "\\`") + "`";
  }

  function genPlaywright(el) {
    var attrs = attrsOf(el);
    var out = [];
    for (var i = 0; i < TESTID_ATTRS.length; i++) {
      var a = TESTID_ATTRS[i];
      if (normalizeWs(attrs[a])) {
        out.push({ code: "getByTestId(" + jsLiteral(attrs[a]) + ")", label: "@" + a, score: 95 });
        break;
      }
    }
    var tag = tagOf(el);
    var role = attrs.role || "";
    var name = attrs["aria-label"] || directText(el, 40);
    if (!role) {
      var roleMap = { button: "button", a: "link", input: "textbox", select: "combobox", textarea: "textbox" };
      role = roleMap[tag] || "";
    }
    if (role && name) {
      out.push({ code: "getByRole(" + jsLiteral(role) + ", { name: " + jsLiteral(name) + " })", label: "role + 名称", score: 88 });
    }
    if (normalizeWs(attrs["aria-label"])) {
      out.push({ code: "getByLabel(" + jsLiteral(attrs["aria-label"]) + ")", label: "@aria-label", score: 80 });
    }
    if (normalizeWs(attrs.placeholder)) {
      out.push({ code: "getByPlaceholder(" + jsLiteral(attrs.placeholder) + ")", label: "@placeholder", score: 75 });
    }
    var txt = directText(el, 40);
    if (txt) {
      out.push({ code: "getByText(" + jsLiteral(txt) + ", { exact: true })", label: "文本", score: 68 });
    }
    return out;
  }

  /* ------------------------------------------------------------------ *
   * 表单标签锚定（label anchoring）
   * 参考 cdnkr/xpath-generator 的「label/text anchoring」优先级：
   * 当控件本身没有稳定属性时，用它的 <label> 文本作为锚点最耐用 ——
   * 因为文案是产品/测试都在意的东西，重构时不容易被顺手改掉。
   * ------------------------------------------------------------------ */
  function allText(el, limit) {
    return normalizeWs(el && el.textContent ? el.textContent : "").slice(0, limit || 120);
  }

  function labelTextFor(el) {
    var attrs = attrsOf(el);

    // 1) <label for="someId"> 显式关联
    var eid = normalizeWs(attrs.id);
    if (eid) {
      var labs = visibleNodes(evalNodes("//label[@for=" + xpathLiteral(eid) + "]"));
      for (var i = 0; i < labs.length; i++) {
        var t1 = normalizeWs(directText(labs[i], 60)) || allText(labs[i], 60);
        if (t1) return t1;
      }
    }

    // 2) aria-labelledby 指向的节点
    var ref = normalizeWs(attrs["aria-labelledby"]);
    if (ref) {
      var ids = ref.split(/\s+/).slice(0, 2);
      for (var j = 0; j < ids.length; j++) {
        var tgts = visibleNodes(evalNodes("//*[@id=" + xpathLiteral(ids[j]) + "]"));
        for (var k = 0; k < tgts.length; k++) {
          var t2 = allText(tgts[k], 60);
          if (t2) return t2;
        }
      }
    }

    // 3) <label> 直接包裹控件
    var cur = el.parentElement;
    while (cur) {
      if (tagOf(cur) === "label") {
        var t3 = normalizeWs(directText(cur, 60));
        if (t3) return t3;
        break;
      }
      cur = cur.parentElement;
    }
    return "";
  }

  function labelAnchoredXpaths(el) {
    var tag = tagOf(el);
    if (["input", "textarea", "select", "button", "a", "output"].indexOf(tag) === -1) return [];
    var txt = labelTextFor(el);
    if (!txt || txt.length > 60) return [];
    var lit = xpathLiteral(txt);
    var meta = { strategy: "label", labelText: txt };
    // 每条候选都带 tag 约束，避免 following-sibling::*[1] 这种会指向任意兄弟节点的危险写法
    return [
      ["//label[normalize-space()=" + lit + "]//" + tag, meta],
      ["//label[normalize-space()=" + lit + "]/following-sibling::" + tag + "[1]", meta],
      ["//label[normalize-space()=" + lit + "]/following::" + tag + "[1]", meta]
    ];
  }

  /* ------------------------------------------------------------------ *
   * 候选总入口
   * ------------------------------------------------------------------ */
  function labelFor(m) {
    switch (m.strategy) {
      case "testid": return "测试属性 @" + m.attr;
      case "id": return "id 定位";
      case "id_dynamic": return "id 定位（动态）";
      case "semantic": return "语义属性 @" + m.attr;
      case "label": return "标签锚定：" + m.labelText;
      case "text": return "精确文本";
      case "class": return "class=" + m.cls;
      case "combo": return "多属性组合";
      case "index": return "位置索引";
      case "list": return "列表模式";
      default: return "属性定位";
    }
  }

  // 稳定祖先限定重复目标；不依赖中间包装层，也不改动网页 DOM。
  function ancestorAnchoredXpaths(el) {
    var tag = tagOf(el);
    var endings = [];
    candidatePredicates(el).forEach(function (pair) {
      var pred = pair[0], meta = pair[1];
      if (["testid", "id", "semantic", "text"].indexOf(meta.strategy) < 0) return;
      var ending = tag + "[" + pred + "]";
      if (!locatesOnly("//" + ending, el)) endings.push([ending, Math.min(76, STRATEGY_BASE[meta.strategy])]);
    });
    if (!locatesOnly("//" + tag, el)) endings.push([tag, 70]);
    if (!endings.length) return [];
    var out = [], seen = Object.create(null), ancestor = el.parentElement;
    for (var depth = 0; ancestor && depth < 6; depth++, ancestor = ancestor.parentElement) {
      var preds = candidatePredicates(ancestor);
      for (var i = 0; i < preds.length; i++) {
        if (["testid", "id", "semantic"].indexOf(preds[i][1].strategy) < 0) continue;
        var anchor = "//" + tagOf(ancestor) + "[" + preds[i][0] + "]";
        if (!locatesOnly(anchor, ancestor)) continue;
        for (var j = 0; j < endings.length; j++) {
          var xp = anchor + "//" + endings[j][0];
          if (!seen[xp] && locatesOnly(xp, el)) {
            seen[xp] = true;
            out.push([xp, { scoreBase: endings[j][1], anchor: tagOf(ancestor) }]);
            if (out.length >= 4) return out;
          }
        }
      }
    }
    return out;
  }

  function genForElement(el) {
    var cands = [];
    var seen = {};

    function push(xp, label, strategy, note, warn, scoreBase) {
      xp = String(xp || "").trim();
      if (!xp || seen[xp]) return;
      seen[xp] = 1;
      var nodes = visibleNodes(evalNodes(xp));
      var n = nodes.length;
      // 「唯一」必须同时满足：只匹配 1 个节点，且那个节点就是目标本身。
      // 只看数量会把「唯一但指错元素」的 XPath 误评为稳定。
      var hit = (n === 1 && nodes[0] === el);
      var score = applyPenalty(scoreBase == null ? (STRATEGY_BASE[strategy] || 50) : scoreBase, xp, xp.split("/").length - 1);
      if (!hit) {
        score = Math.min(score, 55);
        if (!warn && n === 1) warn = "唯一但指向了别的节点";
      }
      cands.push({
        xpath: xp,
        label: label,
        strategy: strategy,
        count: n,
        unique: hit,
        score: score,
        level: stabilityLabel(score),
        note: note || "",
        warn: warn || ""
      });
    }

    // 1) 最短唯一 XPath
    var mini = minimalXPath(el);
    push(mini[0], "最短唯一 XPath", mini[2].strategy || "path", mini[1] + " 级路径", mini[2].warn || "");

    // 2) 逐策略候选
    var tag = tagOf(el);
    var preds = candidatePredicates(el);
    for (var i = 0; i < preds.length; i++) {
      push("//" + tag + "[" + preds[i][0] + "]", labelFor(preds[i][1]), preds[i][1].strategy, "", preds[i][1].warn || "");
    }

    // 3) 表单标签锚定
    var anchored = labelAnchoredXpaths(el);
    for (var q = 0; q < anchored.length; q++) {
      push(anchored[q][0], "标签锚定：" + anchored[q][1].labelText, "label", "表单控件缺稳定属性时最耐用", "");
    }

    var ancestorCands = ancestorAnchoredXpaths(el);
    for (var ac = 0; ac < ancestorCands.length; ac++) {
      push(ancestorCands[ac][0], "稳定祖先锚定", "ancestor", "用祖先属性限定范围，跳过中间包装层", "", ancestorCands[ac][1].scoreBase);
    }

    // 4) 绝对路径兜底
    push(absoluteXPath(el), "绝对路径", "path", "结构变化即失效，仅兜底");

    // 5) 列表模式
    var lx = listXPath(el);
    if (lx && !seen[lx]) {
      var lnodes = visibleNodes(evalNodes(lx));
      if (lnodes.length > 1) {
        seen[lx] = 1;
        cands.push({
          xpath: lx, label: "列表模式（同类集合）", strategy: "list",
          count: lnodes.length, unique: false, score: 66, level: "一般",
          note: "匹配 " + lnodes.length + " 个同类元素，适合批量提取", warn: ""
        });
      }
    }

    cands.sort(function (a, b) {
      if (a.unique !== b.unique) return a.unique ? -1 : 1;
      if (a.score !== b.score) return b.score - a.score;
      return a.xpath.length - b.xpath.length;
    });

    var best = "";
    for (var b = 0; b < cands.length; b++) {
      if (cands[b].unique) { best = cands[b].xpath; break; }
    }
    if (!best && cands.length) best = cands[0].xpath;

    var dynId = "";
    if (normalizeWs(attrsOf(el).id)) dynId = isDynamicValue(attrsOf(el).id)[1];

    return {
      target: {
        node: el,
        tag: tag,
        attrs: attrsOf(el),
        text: fullText(el, 120),
        dynamicId: dynId
      },
      best: best,
      xpath: cands,
      css: genCss(el),
      playwright: genPlaywright(el)
    };
  }

  /* ------------------------------------------------------------------ *
   * 页面扫描 / 批量验证
   * ------------------------------------------------------------------ */
  var INTERACTIVE_TAGS = { a: 1, button: 1, input: 1, select: 1, textarea: 1, option: 1, label: 1, summary: 1 };
  var INTERACTIVE_ROLES = {
    button: 1, link: 1, checkbox: 1, radio: 1, tab: 1, menuitem: 1,
    textbox: 1, combobox: 1, switch: 1, option: 1
  };

  function scanPage(limit) {
    limit = limit || 400;
    var out = [];
    var all = document.body ? document.body.querySelectorAll("*") : [];
    for (var i = 0; i < all.length && out.length < limit; i++) {
      var el = all[i];
      if (isOurNode(el)) continue;
      var tag = tagOf(el);
      var role = el.getAttribute("role") || "";
      var interactive =
        INTERACTIVE_TAGS[tag] ||
        INTERACTIVE_ROLES[role] ||
        el.hasAttribute("onclick") ||
        el.hasAttribute("data-testid") ||
        el.hasAttribute("contenteditable");
      if (!interactive) continue;
      if (tag === "input" && el.getAttribute("type") === "hidden") continue;
      var mini = minimalXPath(el);
      var score = applyPenalty(STRATEGY_BASE[mini[2].strategy || "path"] || 50, mini[0], mini[1]);
      out.push({
        node: el,
        tag: tag,
        text: directText(el, 60),
        xpath: mini[0],
        score: score,
        level: stabilityLabel(score)
      });
    }
    out.sort(function (a, b) { return b.score - a.score; });
    return out;
  }

  function looksLikeCss(sel) {
    var s = String(sel).trim();
    if (!s) return false;
    if (s.charAt(0) === "/" || s.charAt(0) === "(") return false;
    if (s.indexOf("getBy") === 0) return false;
    return true;
  }

  /* ------------------------------------------------------------------ *
   * 定位器自愈建议（Healenium 式）
   *
   * 页面改版后老 XPath 会失配（count == 0）。这里从**选择器字符串本身**反推出
   * 当初想找什么（标签 / 属性值 / class / 文案），再在现在的 DOM 里按相似度找
   * 最像的那个元素，给出一条可用的替代 XPath。
   *
   * 相似度维度与权重参考 Healenium 的 Scored<Node>，阈值取它默认的 0.6：
   *     标签 0.25 | 属性 0.35 | class 0.20 | 文案 0.20
   * ------------------------------------------------------------------ */
  var HEAL_THRESHOLD = 0.6;

  function tokensOf(s) {
    var m = String(s == null ? "" : s).toLowerCase().match(/[a-z0-9]+/g);
    return m ? m : [];
  }

  function tokenSet(s) {
    var out = {};
    var t = tokensOf(s);
    for (var i = 0; i < t.length; i++) out[t[i]] = 1;
    return out;
  }

  function setKeys(o) { return Object.keys(o); }
  function setSize(o) { return Object.keys(o).length; }
  function intersect(a, b) {
    var out = {};
    var ka = Object.keys(a);
    for (var i = 0; i < ka.length; i++) if (b[ka[i]]) out[ka[i]] = 1;
    return out;
  }
  function unionSize(a, b) {
    var out = {};
    var k;
    for (k in a) if (a[k]) out[k] = 1;
    for (k in b) if (b[k]) out[k] = 1;
    return Object.keys(out).length;
  }

  function bigrams(s) {
    s = String(s == null ? "" : s).toLowerCase();
    if (s.length < 2) return s ? { [s]: 1 } : {};
    var out = {};
    for (var i = 0; i < s.length - 1; i++) out[s.slice(i, i + 2)] = 1;
    return out;
  }

  // 两个字符串的相似度 0~1（Sørensen–Dice 二元组 + token Jaccard + 包含加成）
  function similarText(a, b) {
    a = String(a == null ? "" : a).trim().toLowerCase();
    b = String(b == null ? "" : b).trim().toLowerCase();
    if (!a || !b) return 0;
    if (a === b) return 1;

    var ba = bigrams(a), bb = bigrams(b);
    var sa = setSize(ba), sb = setSize(bb);
    var dice = (sa + sb) ? (2 * setSize(intersect(ba, bb)) / (sa + sb)) : 0;

    var ta = tokenSet(a), tb = tokenSet(b);
    var jac = (setSize(ta) && setSize(tb)) ? (setSize(intersect(ta, tb)) / unionSize(ta, tb)) : 0;

    var base = Math.max(dice, jac);
    if (a.indexOf(b) !== -1 || b.indexOf(a) !== -1) base = Math.min(1, base + 0.15);
    return base;
  }

  // 抓出 contains(..., ' X ') 里的 class token（内部有嵌套括号，必须做括号配对）
  function extractContainsClass(sel) {
    var out = [];
    var i = 0;
    while (true) {
      i = sel.indexOf("contains(", i);
      if (i < 0) break;
      var start = i + "contains(".length;
      var depth = 1, j = start;
      while (j < sel.length && depth) {
        if (sel.charAt(j) === "(") depth++;
        else if (sel.charAt(j) === ")") depth--;
        j++;
      }
      var inner = sel.slice(start, j - 1);
      i = j;
      if (inner.indexOf("@class") === -1) continue;
      var lits = inner.match(/'([^']*)'/g) || [];
      if (lits.length) {
        var tok = lits[lits.length - 1].replace(/^'|'$/g, "").trim();
        if (tok) out.push(tok);
      }
    }
    return out;
  }

  function parseSelectorHints(selector) {
    var sel = String(selector || "");
    var hints = { tag: "", attrs: [], classes: [], text: "" };

    var tm = /^\(?\s*\/{1,2}([a-zA-Z][\w-]*)/.exec(sel.trim());
    if (tm) hints.tag = tm[1].toLowerCase();

    var re = /@([\w:.-]+)\s*=\s*(?:'([^']*)'|"([^"]*)")/g, m;
    while ((m = re.exec(sel)) !== null) {
      hints.attrs.push([m[1], m[2] !== undefined ? m[2] : (m[3] || "")]);
    }

    hints.classes = extractContainsClass(sel);

    var xt = /(?:normalize-space\(\s*text\(\)\s*\)|text\(\))\s*=\s*(?:'([^']*)'|"([^"]*)")/.exec(sel);
    if (xt) hints.text = xt[1] !== undefined ? xt[1] : (xt[2] || "");

    return hints;
  }

  function parseCssHints(selector) {
    var sel = String(selector || "").trim();
    var hints = { tag: "", attrs: [], classes: [], text: "" };
    var m = /^([a-zA-Z][\w-]*)/.exec(sel);
    if (m) hints.tag = m[1].toLowerCase();
    var cm = sel.match(/\.([\w-]+)/g) || [];
    hints.classes = cm.map(function (c) { return c.slice(1); });
    var am = /\[([\w-]+)\s*=\s*['"]?([^'"]*)['"]?\]/g, a;
    while ((a = am.exec(sel)) !== null) hints.attrs.push([a[1], a[2]]);
    var im = /#([\w-]+)/.exec(sel);
    if (im) hints.attrs.push(["id", im[1]]);
    return hints;
  }

  // class 维度相似度。BEM 风格里「第一个词」通常是块名
  // （cart-link / cart-entry 都是 cart 块），命中要额外加分。
  function classSimilarity(want, elClasses) {
    var wantT = {}, elT = {}, i, k;
    for (i = 0; i < want.length; i++) { var wt = tokenSet(want[i]); for (k in wt) wantT[k] = 1; }
    if (!setSize(wantT)) return [0, ""];
    for (i = 0; i < elClasses.length; i++) { var et = tokenSet(elClasses[i]); for (k in et) elT[k] = 1; }

    var overlap = setSize(intersect(wantT, elT)) / setSize(wantT);
    var best = Math.max(overlap, similarText(want.join(" "), elClasses.join(" ")));
    var hit = intersect(wantT, elT);
    if (setSize(hit)) best = Math.min(1, best + 0.15);
    var reason = setSize(hit) ? ("class 命中：" + setKeys(hit).sort().slice(0, 3).join(", ")) : "";
    return [best, reason];
  }

  function healScore(el, hints) {
    var reasons = [];
    var elTag = tagOf(el);
    if (hints.tag && elTag !== hints.tag) return [0, []];

    var attrs = attrsOf(el);
    var dims = [];
    if (hints.tag) { dims.push([0.25, 1]); reasons.push("标签仍为 <" + hints.tag + ">"); }

    if (hints.attrs.length) {
      var best = 0;
      for (var i = 0; i < hints.attrs.length; i++) {
        var name = hints.attrs[i][0], val = hints.attrs[i][1];
        if (attrs[name] !== undefined) {
          var sim = similarText(val, attrs[name]);
          if (sim >= 0.999) reasons.push("@" + name + " 值未变");
          else if (sim >= 0.6) reasons.push("@" + name + " 值近似：" + attrs[name]);
          best = Math.max(best, sim);
          continue;
        }
        for (var k2 in attrs) {
          if (!Object.prototype.hasOwnProperty.call(attrs, k2)) continue;
          var s2 = similarText(val, attrs[k2]);
          if (s2 >= 0.7) { best = Math.max(best, s2 * 0.85); reasons.push("原 @" + name + " 的值搬到了 @" + k2); break; }
        }
      }
      dims.push([0.35, best]);
    }

    if (hints.classes.length) {
      var cs = classSimilarity(hints.classes, stableClassTokens(attrs["class"] || ""));
      if (cs[1]) reasons.push(cs[1]);
      dims.push([0.20, cs[0]]);
    }

    if (hints.text) {
      var ts = similarText(hints.text, directText(el, 80));
      if (ts >= 0.6) reasons.push("文案接近");
      dims.push([0.20, ts]);
    }

    if (!dims.length) return [0, []];
    var tw = 0, acc = 0;
    for (var d = 0; d < dims.length; d++) { tw += dims[d][0]; acc += dims[d][0] * dims[d][1]; }
    return [Math.min(1, acc / tw), reasons];
  }

  function healFromHints(hints, limit, maxPool) {
    if (!hints.tag && !hints.attrs.length && !hints.classes.length && !hints.text) return [];
    var poolXp = hints.tag ? ("//" + hints.tag) : "//*";
    var pool = visibleNodes(evalNodes(poolXp)) || [];
    var cap = maxPool || 4000;
    if (pool.length > cap) pool = pool.slice(0, cap);

    var scored = [];
    for (var i = 0; i < pool.length; i++) {
      var el = pool[i];
      if (!el || el.nodeType !== 1) continue;
      var r = healScore(el, hints);
      if (r[0] >= HEAL_THRESHOLD) scored.push([r[0], el, r[1]]);
    }
    scored.sort(function (a, b) { return b[0] - a[0]; });

    var out = [], seen = {};
    for (var j = 0; j < scored.length && out.length < (limit || 3); j++) {
      var xp = minimalXPath(scored[j][1])[0];
      if (!xp || seen[xp]) continue;
      seen[xp] = 1;
      out.push({
        xpath: xp,
        score: Math.round(scored[j][0] * 1000) / 1000,
        tag: tagOf(scored[j][1]),
        text: directText(scored[j][1], 60),
        reason: scored[j][2].filter(function (v, idx, arr) { return arr.indexOf(v) === idx; }).join("、"),
        confidence: scored[j][0] >= 0.8 ? "高" : (scored[j][0] >= 0.7 ? "中" : "低")
      });
    }
    return out;
  }

  function healSelector(selector, limit) {
    return healFromHints(parseSelectorHints(selector), limit);
  }

  function healCssSelector(selector, limit) {
    return healFromHints(parseCssHints(selector), limit);
  }

  function verifyBatch(selectors) {
    var results = [];
    for (var i = 0; i < selectors.length; i++) {
      var sel = String(selectors[i] || "").trim();
      if (!sel) continue;
      var item = { selector: sel, type: "", valid: false, count: 0, error: "", node: null, note: "", heal: [] };
      if (sel.indexOf("getBy") === 0) {
        item.type = "playwright";
        item.note = "Playwright 定位器需在测试代码中运行验证";
        results.push(item);
        continue;
      }
      if (looksLikeCss(sel)) {
        item.type = "css";
        var cnt = cssCount(sel);
        if (cnt === null) item.error = "CSS 选择器无效";
        else { item.valid = true; item.count = cnt; }
        // 失配才给自愈建议（命中数 > 0 说明还能用）
        if (item.valid && cnt === 0) item.heal = healCssSelector(sel);
        results.push(item);
        continue;
      }
      item.type = "xpath";
      var nodes = evalNodes(sel);
      if (nodes === null) {
        item.error = "XPath 表达式无效";
      } else {
        var vis = visibleNodes(nodes);
        item.valid = true;
        item.count = vis.length;
        if (vis.length && vis[0].nodeType === 1) item.node = vis[0];
        if (vis.length === 0) item.heal = healSelector(sel);
      }
      results.push(item);
    }
    return results;
  }

  /* ------------------------------------------------------------------ *
   * 导出
   * ------------------------------------------------------------------ */
  global.XPathStudioEngine = {
    UI_ROOT_ID: UI_ROOT_ID,
    tagOf: tagOf,
    attrsOf: attrsOf,
    directText: directText,
    fullText: fullText,
    isOurNode: isOurNode,
    xpathLiteral: xpathLiteral,
    isDynamicValue: isDynamicValue,
    stableClassTokens: stableClassTokens,
    isHashyToken: isHashyToken,
    stabilityLabel: stabilityLabel,
    applyPenalty: applyPenalty,
    evalNodes: evalNodes,
    validate: validate,
    minimalXPath: minimalXPath,
    absoluteXPath: absoluteXPath,
    listXPath: listXPath,
    genForElement: genForElement,
    labelTextFor: labelTextFor,
    labelAnchoredXpaths: labelAnchoredXpaths,
    genCss: genCss,
    genPlaywright: genPlaywright,
    scanPage: scanPage,
    verifyBatch: verifyBatch,
    healSelector: healSelector,
    healCssSelector: healCssSelector,
    parseSelectorHints: parseSelectorHints,
    parseCssHints: parseCssHints,
    similarText: similarText,
    HEAL_THRESHOLD: HEAL_THRESHOLD,
    STRATEGY_BASE: STRATEGY_BASE
  };
})(typeof window !== "undefined" ? window : globalThis);
