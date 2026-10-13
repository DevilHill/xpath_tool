/* ============================================================
 * XPath Studio · 内容脚本
 * 元素拾取（Ctrl+左键） · 页面实时高亮 · 抓取结果回传桌面版
 *
 * 拾取/高亮使用**独立的覆盖层**（Shadow DOM），不依赖面板是否打开，
 * 这样桌面版「抓取元素」按钮驱动的流程可以在不弹出面板的情况下完成。
 * ============================================================ */
(function () {
  "use strict";

  if (window.__XPS_CONTENT_LOADED__) return;
  window.__XPS_CONTENT_LOADED__ = true;

  var Engine = window.XPathStudioEngine;
  var Panel = window.XPathStudioPanel;
  if (!Engine || !Panel) {
    console.warn("[XPath Studio] 引擎或面板未加载");
    return;
  }

  var PANEL_HOST_ID = Engine.UI_ROOT_ID;          // __xpath_studio_root__
  var OVERLAY_HOST_ID = "__xpath_studio_overlay__";

  /* ------------------------------------------------------------------ *
   * 独立覆盖层
   * ------------------------------------------------------------------ */
  var OVERLAY_STYLE = `
  .ov-hl, .ov-pick {
    position: absolute; pointer-events: none; border-radius: 3px;
    box-shadow: 0 0 0 1px rgba(255,255,255,.7);
  }
  .ov-hl { background: rgba(16,185,129,.20); outline: 1px solid #10b981; }
  .ov-hl.primary { background: rgba(99,102,241,.26); outline: 2px solid #6366f1; }
  .ov-hl-tag {
    position: absolute; top: -16px; left: 0; padding: 0 5px; height: 15px; line-height: 15px;
    font-family: Consolas,monospace; font-size: 10px; border-radius: 3px;
    background: #10b981; color: #fff; white-space: nowrap;
  }
  .ov-hl.primary .ov-hl-tag { background: #6366f1; }

  .ov-pick {
    background: rgba(99,102,241,.30); outline: 2px solid #6366f1;
    box-shadow: 0 0 0 1px rgba(255,255,255,.85), 0 0 22px rgba(99,102,241,.55);
  }
  .ov-pick-size {
    position: absolute; top: -17px; right: 0; padding: 0 6px; height: 15px; line-height: 15px;
    font-family: Consolas,monospace; font-size: 10px; border-radius: 3px;
    background: #6366f1; color: #fff; white-space: nowrap;
  }
  .ov-tip {
    position: absolute; padding: 5px 9px; border-radius: 6px; font-size: 11px;
    font-family: Consolas,monospace; background: #1f2430; color: #fff;
    white-space: nowrap; max-width: 460px; overflow: hidden; text-overflow: ellipsis;
    box-shadow: 0 4px 16px rgba(0,0,0,.3);
  }
  .ov-bar {
    position: fixed; left: 50%; transform: translateX(-50%); bottom: 26px;
    display: flex; align-items: center; gap: 8px;
    padding: 9px 16px; border-radius: 999px; font-size: 12.5px;
    font-family: "PingFang SC","Microsoft YaHei UI","Segoe UI",system-ui,sans-serif;
    background: rgba(31,36,48,.96); color: #fff; white-space: nowrap;
    box-shadow: 0 10px 30px rgba(0,0,0,.36); pointer-events: none; z-index: 5;
  }
  .ov-bar kbd {
    background: linear-gradient(135deg,#6366f1,#8b5cf6); border-radius: 5px;
    padding: 2px 7px; font-family: Consolas,monospace; font-size: 11px;
  }
  .ov-bar b { color: #a5b4fc; }
  .ov-flash {
    position: fixed; left: 50%; transform: translateX(-50%); bottom: 26px;
    padding: 9px 16px; border-radius: 999px; font-size: 12.5px;
    font-family: "PingFang SC","Microsoft YaHei UI","Segoe UI",system-ui,sans-serif;
    background: rgba(16,185,129,.97); color: #fff; white-space: nowrap;
    box-shadow: 0 10px 30px rgba(0,0,0,.36); pointer-events: none; z-index: 6;
  }
  .ov-flash.err { background: rgba(239,68,68,.97); }
  .ov-review {
    position: fixed; right: 12px; bottom: 12px; width: min(350px, calc(100vw - 40px));
    max-height: calc(100vh - 40px); overflow: auto; padding: 14px;
    background: #fff; color: #172033; border: 1px solid #bfc8da; border-radius: 10px;
    box-shadow: 0 8px 30px #0003; pointer-events: auto; z-index: 8;
    font: 13px/1.6 "Microsoft YaHei UI",sans-serif; white-space: normal;
  }
  .ov-review code { display: block; white-space: pre-wrap; overflow-wrap: anywhere; margin: 8px 0; }
  .ov-review button { cursor: pointer !important; padding: 6px 10px; margin: 5px 6px 0 0;
    color: #172033; background: #eef2ff; border: 1px solid #bfc8da; border-radius: 6px; }
  .ov-review button:disabled { opacity: .5; }
  @media (prefers-color-scheme: dark) {
    .ov-review { background: #202738; color: #eef2ff; border-color: #59647a; }
    .ov-review button { background: #35405b; color: #eef2ff; border-color: #59647a; }
  }
  `;

  var ovHost = null;
  var ovRoot = null;
  var ovBox = null;   // 高亮框容器

  function ensureOverlay() {
    if (ovHost && ovHost.isConnected && ovRoot) return ovRoot;
    ovHost = document.createElement("div");
    ovHost.id = OVERLAY_HOST_ID;
    ovHost.setAttribute("data-xps", "1");
    ovHost.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;pointer-events:none;z-index:2147483646;";
    ovRoot = ovHost.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = OVERLAY_STYLE;
    ovRoot.appendChild(style);
    ovBox = document.createElement("div");
    ovRoot.appendChild(ovBox);
    (document.documentElement || document.body).appendChild(ovHost);
    return ovRoot;
  }

  function ovEl(cls, text) {
    var e = document.createElement("div");
    e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  /* ------------------------------------------------------------------ *
   * 匹配高亮（校验 XPath 后）
   * ------------------------------------------------------------------ */
  var hlNodes = [];
  var hlPrimary = null;
  var loopTimer = null;

  function drawHighlight() {
    if (!ovBox) return;
    ovBox.textContent = "";
    if (!hlNodes.length) return;
    var frag = document.createDocumentFragment();
    for (var i = 0; i < hlNodes.length; i++) {
      var n = hlNodes[i];
      if (!n || n.nodeType !== 1 || n.isConnected === false) continue;
      var r = n.getBoundingClientRect();
      if (r.width < 1 && r.height < 1) continue;
      var box = ovEl("ov-hl" + (n === hlPrimary ? " primary" : ""));
      box.style.left = r.left + "px";
      box.style.top = r.top + "px";
      box.style.width = r.width + "px";
      box.style.height = r.height + "px";
      if (r.width > 30 && r.height > 18) {
        box.appendChild(ovEl("ov-hl-tag", (i + 1) + " <" + Engine.tagOf(n) + ">"));
      }
      frag.appendChild(box);
    }
    ovBox.appendChild(frag);
  }

  function startLoop() { if (!loopTimer) loopTimer = setInterval(drawHighlight, 120); }
  function stopLoop() { if (loopTimer) { clearInterval(loopTimer); loopTimer = null; } }

  function setHighlight(nodes, primary) {
    ensureOverlay();
    hlNodes = (nodes || []).filter(function (n) { return n && n.nodeType === 1; });
    hlPrimary = primary || null;
    drawHighlight();
    if (hlNodes.length) startLoop(); else stopLoop();
  }

  function clearHighlight() {
    hlNodes = [];
    hlPrimary = null;
    if (ovBox) ovBox.textContent = "";
    stopLoop();
  }

  window.addEventListener("scroll", drawHighlight, true);
  window.addEventListener("resize", drawHighlight, true);

  /* ------------------------------------------------------------------ *
   * 提示条 / 轻提示
   * ------------------------------------------------------------------ */
  var barEl = null;
  var flashEl = null;
  var flashTimer = null;

  function showBar(html) {
    ensureOverlay();
    if (!barEl || !barEl.isConnected) {
      barEl = ovEl("ov-bar");
      ovRoot.appendChild(barEl);
    }
    barEl.innerHTML = html;
  }

  function hideBar() {
    if (barEl) { barEl.remove(); barEl = null; }
  }

  function flash(text, isErr) {
    ensureOverlay();
    if (flashEl) flashEl.remove();
    flashEl = ovEl("ov-flash" + (isErr ? " err" : ""), text);
    ovRoot.appendChild(flashEl);
    clearTimeout(flashTimer);
    flashTimer = setTimeout(function () {
      if (flashEl) { flashEl.remove(); flashEl = null; }
    }, 2000);
  }

  /* ------------------------------------------------------------------ *
   * 元素拾取
   * ------------------------------------------------------------------ */
  var picking = false;
  var pickBox = null;
  var pickSize = null;
  var pickTip = null;
  var lastHover = null;
  var cursorStyle = null;
  var pickSessionId = null;
  var locked = false;
  var paused = false;
  var reviewEl = null;
  var hoverLeaf = null;
  var hoverTrail = [];
  var sending = false;

  function ownEvent(e) {
    return e.composedPath && e.composedPath().some(function (n) {
      return n === ovHost || (n && n.id === PANEL_HOST_ID);
    });
  }

  function pickHint() {
    showBar('悬停定位 · <kbd>↑ / ↓</kbd> 父子层级 · <kbd>Ctrl</kbd>＋左键锁定 · <kbd>Esc</kbd> 取消');
  }

  function changeLevel(up) {
    if (!lastHover) return;
    if (up && lastHover.parentElement && !isOurElement(lastHover.parentElement)) {
      hoverTrail.push(lastHover);
      lastHover = lastHover.parentElement;
    } else if (!up && hoverTrail.length) lastHover = hoverTrail.pop();
    drawPick();
    if (locked) renderReview();
  }

  function cancelPick() {
    notifyBridgeStatus({ kind: "cancel" });
    stopPicking();
    flash("已取消拾取", true);
  }

  function renderReview() {
    if (reviewEl) reviewEl.remove();
    reviewEl = ovEl("ov-review");
    reviewEl.setAttribute("role", "dialog");
    reviewEl.setAttribute("aria-label", "确认抓取元素");
    reviewEl.appendChild(ovEl("", "已锁定：" + describe(lastHover)));
    var result = Engine.genForElement(lastHover);
    var code = document.createElement("code");
    code.textContent = result.best || "未生成 XPath";
    reviewEl.appendChild(code);
    var status = ovEl("", (window.top === window ? "当前网页" : "当前 iframe 内") +
      "的 XPath；Enter 确认，Esc 取消");
    reviewEl.appendChild(status);
    function button(text, name, fn) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = text; b.dataset.action = name;
      b.addEventListener("click", fn); reviewEl.appendChild(b); return b;
    }
    button("父元素 ↑", "parent", function () { changeLevel(true); });
    button("返回子元素 ↓", "child", function () { changeLevel(false); }).disabled = !hoverTrail.length;
    button("重新选择", "retry", function () {
      function resume() {
        locked = false; hoverLeaf = null; hoverTrail = []; lastHover = null;
        if (reviewEl) { reviewEl.remove(); reviewEl = null; }
        if (pickBox) pickBox.style.display = "none";
        if (pickTip) pickTip.style.display = "none";
        pickHint();
      }
      if (!pickSessionId) { resume(); return; }
      chrome.runtime.sendMessage({ type: "pick-resume", sessionId: pickSessionId }, function (r) {
        if (chrome.runtime.lastError || !r || !r.ok) { status.textContent = "无法恢复，请取消后重新抓取"; return; }
        resume();
      });
    });
    button("取消", "cancel", cancelPick);
    var confirm = button("确认抓取", "confirm", function () {
      if (sending) return;
      if (!lastHover || !lastHover.isConnected) { status.textContent = "元素已被页面移除，请重新选择"; return; }
      sending = true;
      Array.from(reviewEl.querySelectorAll("button")).forEach(function (b) { b.disabled = true; });
      var target = lastHover;
      var activeSession = pickSessionId;
      var generated = Engine.genForElement(target);
      // 独立面板不依赖桌面版在线：本地结果照常生成，回传仅作为可选同步。
      if (!activeSession) {
        sending = false; stopPicking(); selectElement(target); return;
      }
      reportPicked(target, generated, function (ok, error) {
        if (picking && pickSessionId !== activeSession) return;
        sending = false;
        if (!ok) {
          if (reviewEl) { renderReview(); reviewEl.appendChild(ovEl("", error)); }
          return;
        }
        stopPicking();
        selectedEl = target;
        if (panelReady()) { Panel.renderGen(generated); Panel.setXPath(generated.best || ""); }
        if (generated.best) validateXPath(generated.best, target);
      });
    });
    ovRoot.appendChild(reviewEl);
    confirm.focus();
  }

  function isOurElement(el) {
    if (!el) return true;
    var root = el.getRootNode ? el.getRootNode() : null;
    if (root && root.host && (root.host.id === PANEL_HOST_ID || root.host.id === OVERLAY_HOST_ID)) return true;
    if (root === document) return Engine.isOurNode(el);
    return false;
  }

  function setCrosshair(on) {
    if (on) {
      if (!cursorStyle) {
        cursorStyle = document.createElement("style");
        cursorStyle.setAttribute("data-xps", "1");
        cursorStyle.textContent = "*, *::before, *::after { cursor: crosshair !important; }";
        document.documentElement.appendChild(cursorStyle);
      }
    } else if (cursorStyle) {
      cursorStyle.remove();
      cursorStyle = null;
    }
  }

  function describe(el) {
    var a = Engine.attrsOf(el);
    var s = "<" + Engine.tagOf(el);
    if (a.id) s += "#" + a.id;
    var cls = (a["class"] || "").split(/\s+/).filter(Boolean).slice(0, 3);
    if (cls.length) s += "." + cls.join(".");
    s += ">";
    var t = Engine.directText(el, 30);
    if (t) s += " " + t;
    return s;
  }

  function onHover(e) {
    if (!picking || locked || paused || ownEvent(e)) return;
    var el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el || isOurElement(el)) return;
    if (el !== hoverLeaf) { hoverLeaf = el; lastHover = el; hoverTrail = []; }
    drawPick();
  }

  function drawPick() {
    if (!picking || paused || !lastHover || !lastHover.isConnected) return;
    var el = lastHover;
    ensureOverlay();
    if (!pickBox || !pickBox.isConnected) {
      pickBox = ovEl("ov-pick");
      ovRoot.appendChild(pickBox);
    }
    if (!pickTip || !pickTip.isConnected) {
      pickTip = ovEl("ov-tip");
      ovRoot.appendChild(pickTip);
    }
    pickBox.style.display = "";
    pickTip.style.display = "";
    var r = el.getBoundingClientRect();
    pickBox.style.left = r.left + "px";
    pickBox.style.top = r.top + "px";
    pickBox.style.width = r.width + "px";
    pickBox.style.height = r.height + "px";

    // 尺寸角标
    if (r.width > 40) {
      if (!pickSize || !pickSize.isConnected) {
        pickSize = ovEl("ov-pick-size");
        pickBox.appendChild(pickSize);
      }
      pickSize.textContent = Math.round(r.width) + " × " + Math.round(r.height);
    } else if (pickSize) {
      pickSize.remove();
      pickSize = null;
    }

    pickTip.textContent = describe(el);
    var tw = pickTip.offsetWidth || 200;
    var left = Math.min(Math.max(6, r.left), Math.max(6, window.innerWidth - tw - 8));
    var top = r.top > 30 ? r.top - 26 : r.bottom + 8;
    pickTip.style.left = left + "px";
    pickTip.style.top = top + "px";
  }

  function suppressEvent(e) {
    if (!picking || ownEvent(e)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }

  function onClickCapture(e) {
    if (!picking || ownEvent(e)) return;
    // 拾取期间吞掉所有点击，避免误触页面
    e.preventDefault();
    e.stopImmediatePropagation();
    if (locked || paused || e.button !== 0) return;

    var withModifier = e.ctrlKey || e.metaKey;
    if (!withModifier) {
      // 只按左键 -> 提示需要按住 Ctrl
      showBar('<b>按住</b> <kbd>Ctrl</kbd> <b>再左键点击</b> 选中元素 · <kbd>Esc</kbd> 取消');
      return;
    }

    var hit = document.elementFromPoint(e.clientX, e.clientY);
    var el = hit === hoverLeaf ? lastHover : hit;
    if (!el || isOurElement(el)) return;
    lastHover = el;
    locked = true;
    hideBar();
    drawPick();
    var session = pickSessionId;
    if (!session) { renderReview(); return; }
    chrome.runtime.sendMessage({ type: "pick-lock", sessionId: session }, function (r) {
      if (!picking || pickSessionId !== session) return;
      if (chrome.runtime.lastError || !r || !r.ok) {
        stopPicking(); flash((r && r.error) || "锁定失败，请重新抓取", true); return;
      }
      renderReview();
    });
  }

  function onKeyCapture(e) {
    if (!picking) return;
    if (sending) return;
    if (e.key === "Escape") {
      e.preventDefault(); e.stopImmediatePropagation(); cancelPick();
    } else if (!paused && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      e.preventDefault(); e.stopImmediatePropagation(); changeLevel(e.key === "ArrowUp");
    } else if (locked && e.key === "Enter" && reviewEl) {
      e.preventDefault(); e.stopImmediatePropagation();
      reviewEl.querySelector('[data-action="confirm"]').click();
    }
  }

  function startPicking(hint, sessionId) {
    if (picking) stopPicking();
    picking = true;
    pickSessionId = sessionId || null;
    locked = false; paused = false; sending = false; hoverLeaf = null; hoverTrail = [];
    clearHighlight();
    Panel.setPicking(true);
    setCrosshair(true);
    document.addEventListener("mousemove", onHover, true);
    document.addEventListener("mousedown", suppressEvent, true);
    document.addEventListener("mouseup", suppressEvent, true);
    document.addEventListener("click", onClickCapture, true);
    document.addEventListener("keydown", onKeyCapture, true);
    pickHint();
    window.addEventListener("scroll", drawPick, true);
    window.addEventListener("resize", drawPick, true);
  }

  function stopPicking() {
    if (!picking) return;
    picking = false;
    Panel.setPicking(false);
    document.removeEventListener("mousemove", onHover, true);
    document.removeEventListener("mousedown", suppressEvent, true);
    document.removeEventListener("mouseup", suppressEvent, true);
    document.removeEventListener("click", onClickCapture, true);
    document.removeEventListener("keydown", onKeyCapture, true);
    window.removeEventListener("scroll", drawPick, true);
    window.removeEventListener("resize", drawPick, true);
    setCrosshair(false);
    hideBar();
    if (reviewEl) { reviewEl.remove(); reviewEl = null; }
    locked = false; paused = false; hoverLeaf = null; hoverTrail = []; pickSessionId = null;
    if (pickBox) { pickBox.remove(); pickBox = null; }
    if (pickSize) { pickSize.remove(); pickSize = null; }
    if (pickTip) { pickTip.remove(); pickTip = null; }
    lastHover = null;
  }

  /* ------------------------------------------------------------------ *
   * 选中元素 / 校验 / 回传桌面版
   * ------------------------------------------------------------------ */
  var selectedEl = null;
  var panelMounted = false;

  function panelReady() {
    return panelMounted && Panel.isVisible();
  }

  function selectElement(el) {
    selectedEl = el;
    var res = Engine.genForElement(el);

    if (panelReady()) {
      Panel.selectTab("cand");
      Panel.renderGen(res);
      Panel.setXPath(res.best || "");
    }
    if (res.best) validateXPath(res.best, el);
    reportPicked(el, res);
  }

  function buildPayload(el, res) {
    var a = Engine.attrsOf(el);
    var rect = el.getBoundingClientRect();
    var live = res.best ? Engine.validate(res.best) : null;
    return {
      tag: Engine.tagOf(el),
      id: a.id || "",
      classes: (a["class"] || "").split(/\s+/).filter(Boolean),
      attrs: a,
      text: Engine.directText(el, 160) || "",
      html: (el.outerHTML || "").slice(0, 4000),
      xpath: res.best || "",
      candidates: res.xpath || [],
      css: res.css || null,
      playwright: res.playwright || [],
      target: res.target || null,
      url: location.href,
      title: document.title,
      // 实时页面上的匹配数（以浏览器 DOM 为准，权威）
      matchCount: live && live.valid ? live.count : -1,
      rect: {
        x: Math.round(rect.left), y: Math.round(rect.top),
        w: Math.round(rect.width), h: Math.round(rect.height)
      },
      ts: Date.now()
    };
  }

  function reportPicked(el, res, done) {
    var payload = buildPayload(el, res);
    try {
      chrome.runtime.sendMessage(
        { type: "picked", payload: payload, bridge: Panel.getBridge(), sessionId: pickSessionId },
        function (resp) {
          var error = chrome.runtime.lastError ? chrome.runtime.lastError.message :
            (!resp || !resp.ok ? ((resp && resp.error) || "桌面版未确认收到结果") : "");
          if (error) {
            flash("无法回传：" + error, true);
            if (done) done(false, error);
            return;
          }
          var via = resp && resp.via === "http" ? "（HTTP 兜底）" : "";
          flash("已发送到 XPath Studio" + via);
          if (done) done(true);
        }
      );
    } catch (e) {
      flash("回传失败：" + e.message, true);
      if (done) done(false, e.message);
    }
  }

  function notifyBridgeStatus(payload) {
    try {
      chrome.runtime.sendMessage({ type: "picked-status", payload: payload, sessionId: pickSessionId }, function () {
        void chrome.runtime.lastError;
      });
    } catch (e) { /* 忽略 */ }
  }

  function validateXPath(xp, primary) {
    var v = Engine.validate(xp);
    if (!v.valid) {
      if (panelReady()) {
        Panel.setStatus("✕ 表达式无效：" + v.error, "err");
        Panel.renderMatches([], null);
      }
      clearHighlight();
      return v;
    }
    var n = v.count;
    if (panelReady()) {
      if (n === 0) Panel.setStatus("⚠ 表达式有效，但没有匹配到节点", "warn");
      else if (n === 1) Panel.setStatus("✓ 匹配唯一节点", "ok");
      else Panel.setStatus("⚠ 匹配到 " + n + " 个节点" + (v.truncated ? "（仅显示前 500）" : ""), "warn");
    }

    var nodes = [];
    for (var i = 0; i < v.matches.length; i++) {
      if (v.matches[i].kind === "node") nodes.push(v.matches[i].node);
    }
    if (panelReady()) Panel.renderMatches(v.matches, focusNode);

    var prim = primary || selectedEl;
    if (nodes.indexOf(prim) === -1) prim = nodes[0] || null;
    setHighlight(nodes, prim);
    return v;
  }

  function focusNode(node) {
    if (!node || !node.scrollIntoView) return;
    try { node.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" }); }
    catch (e) { node.scrollIntoView(); }
    hlPrimary = node;
    drawHighlight();
  }

  /* ------------------------------------------------------------------ *
   * 扫描 / AI（面板内使用）
   * ------------------------------------------------------------------ */
  function runScan() {
    Panel.setStatus('<span class="xps-spin"></span>扫描中…', "");
    setTimeout(function () {
      var items = Engine.scanPage();
      Panel.renderScan(items, focusNode);
      Panel.setStatus("扫描完成：找到 " + items.length + " 个可交互元素", "ok");
    }, 30);
  }

  function pageHtml() {
    var html = document.documentElement ? document.documentElement.outerHTML : "";
    if (html.length > 200000) html = html.slice(0, 200000) + "\n<!-- 内容过长已截断 -->";
    return html;
  }

  function runAi(instruction) {
    var bridge = Panel.getBridge();
    Panel.setAiStatus('<span class="xps-spin"></span>正在请求桌面版生成…', "");
    try {
      chrome.runtime.sendMessage(
        { type: "ai-generate", instruction: instruction, html: pageHtml(), bridge: bridge },
        function (resp) {
          if (chrome.runtime.lastError) {
            Panel.setAiStatus("✕ " + chrome.runtime.lastError.message, "err");
            return;
          }
          if (!resp || !resp.ok) {
            Panel.setAiStatus("✕ " + ((resp && resp.error) || "未知错误"), "err");
            return;
          }
          var v = Engine.validate(resp.xpath);
          Panel.setAiStatus((resp.explain ? resp.explain + " " : "") +
            "（本地校验：" + (v.valid ? v.count + " 个匹配" : "无效表达式") + "）", v.valid && v.count === 1 ? "ok" : "warn");
          var all = [resp.xpath].concat(resp.alternatives || []).filter(Boolean);
          Panel.renderAiList(all);
          if (resp.xpath) {
            Panel.setXPath(resp.xpath);
            Panel.selectTab("cand");
            validateXPath(resp.xpath, null);
          }
        }
      );
    } catch (e) {
      Panel.setAiStatus("✕ 无法与扩展后台通信：" + e.message, "err");
    }
  }

  function testBridge(url) {
    Panel.setAiStatus('<span class="xps-spin"></span>测试连接…', "");
    try {
      chrome.runtime.sendMessage({ type: "bridge-test", bridge: url }, function (resp) {
        if (chrome.runtime.lastError) {
          Panel.setAiStatus("✕ " + chrome.runtime.lastError.message, "err");
          return;
        }
        if (resp && resp.ok) {
          Panel.setAiStatus("✓ 桌面版已连接（" + (resp.version || "ok") + "）", "ok");
        } else {
          Panel.setAiStatus("✕ 连接失败：" + ((resp && resp.error) || "请确认桌面版正在运行"), "err");
        }
      });
    } catch (e) {
      Panel.setAiStatus("✕ " + e.message, "err");
    }
  }

  /* ------------------------------------------------------------------ *
   * 面板装配
   * ------------------------------------------------------------------ */
  function ensurePanel(opts) {
    if (panelMounted) return;
    panelMounted = true;
    Panel.mount({
      onPickToggle: function () { picking ? stopPicking() : startPicking(); },
      onValidate: function (xp) { validateXPath(xp, null); },
      onScan: runScan,
      onAi: runAi,
      onBridgeTest: testBridge,
      onClose: function () { Panel.hide(); stopPicking(); clearHighlight(); },
      onToast: function (t) { Panel.setStatus(t, "ok"); }
    }, opts);
  }

  /* ------------------------------------------------------------------ *
   * 消息（来自 background）
   * ------------------------------------------------------------------ */
  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    if (!msg || !msg.type) return;
    if (msg.type === "browser-validate") {
      if (msg.action === "clear") {
        clearHighlight();
        sendResponse({ ok: true, cleared: true });
        return true;
      }
      var result = validateXPath(msg.xpath, null);
      var nodes = (result.matches || []).filter(function (m) { return m.kind === "node"; });
      if (nodes.length) focusNode(nodes[0].node);
      sendResponse({ ok: true, valid: result.valid, error: result.error || "",
        count: result.count, truncated: !!result.truncated, highlighted: nodes.length,
        matches: (result.matches || []).map(function (m) {
          if (m.kind !== "node") return { kind: "value", value: String(m.value).slice(0, 512) };
          var attrs = {};
          Object.keys(m.attrs || {}).slice(0, 20).forEach(function (key) {
            attrs[key] = String(m.attrs[key]).slice(0, 256);
          });
          return { kind: "node", tag: m.tag, attrs: attrs, text: m.text };
        }) });
      return true;
    }

    if (msg.type === "ping") {
      sendResponse({ ok: true, hasPanel: panelMounted, picking: picking });
      return true;
    }
    if (msg.type === "toggle-panel") {
      ensurePanel();
      Panel.toggle();
      if (!Panel.isVisible()) { stopPicking(); clearHighlight(); }
      sendResponse({ ok: true, visible: Panel.isVisible() });
      return true;
    }
    if (msg.type === "show-panel") {
      ensurePanel();
      Panel.show();
      sendResponse({ ok: true });
      return true;
    }
    if (msg.type === "toggle-picker") {
      ensurePanel();
      Panel.show();
      picking ? stopPicking() : startPicking();
      sendResponse({ ok: true, picking: picking });
      return true;
    }

    // 桌面版「抓取元素」按钮驱动：不弹面板，直接在页面上拾取
    if (msg.type === "start-pick") {
      ensurePanel({ hidden: true });
      startPicking(msg.hint, msg.sessionId);
      sendResponse({ ok: true, picking: picking });
      return true;
    }
    if (msg.type === "pause-pick" || msg.type === "resume-pick") {
      if (msg.sessionId !== pickSessionId) { sendResponse({ ok: false }); return true; }
      paused = msg.type === "pause-pick";
      if (paused) {
        hideBar();
        if (pickBox) pickBox.style.display = "none";
        if (pickTip) pickTip.style.display = "none";
      } else pickHint();
      sendResponse({ ok: true }); return true;
    }
    if (msg.type === "stop-pick") {
      if (msg.sessionId && msg.sessionId !== pickSessionId) { sendResponse({ ok: false }); return true; }
      stopPicking();
      sendResponse({ ok: true });
      return true;
    }
    if (msg.type === "bridge-state") {
      // 桌面版连接状态变化：面板可见时同步提示
      var st = msg.state || {};
      if (panelReady() && !st.connected) {
        Panel.setAiStatus("⚠ 与桌面版的实时连接已断开，正在重连…", "warn");
      } else if (panelReady() && st.connected) {
        Panel.setAiStatus("✓ 已连接桌面版实时通道", "ok");
      }
      sendResponse({ ok: true });
      return true;
    }
    return false;
  });

  // 页面卸载时清理
  window.addEventListener("pagehide", function () {
    if (picking) notifyBridgeStatus({ kind: "cancel" });
    stopPicking();
    stopLoop();
  });
})();
