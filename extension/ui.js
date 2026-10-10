/* ============================================================
 * XPath Studio · 页面内浮动面板（Shadow DOM 隔离）
 * ============================================================ */
(function (global) {
  "use strict";

  var HOST_ID = "__xpath_studio_root__";

  var STYLE = `
  * { box-sizing: border-box; }
  .xps {
    position: fixed; width: 396px; max-height: 78vh;
    display: flex; flex-direction: column;
    background: var(--xps-bg); color: var(--xps-fg);
    border: 1px solid var(--xps-border); border-radius: 12px;
    box-shadow: 0 12px 40px rgba(0,0,0,.24), 0 2px 8px rgba(0,0,0,.12);
    font-family: "PingFang SC","Microsoft YaHei UI","Segoe UI",system-ui,-apple-system,sans-serif;
    font-size: 13px; line-height: 1.5; pointer-events: auto; overflow: hidden;
  }
  .xps[hidden] { display: none !important; }

  .xps-head {
    display: flex; align-items: center; gap: 8px;
    padding: 9px 11px; cursor: move; user-select: none;
    background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff;
  }
  .xps-logo {
    width: 20px; height: 20px; border-radius: 6px; flex: 0 0 20px;
    background: rgba(255,255,255,.22); display: grid; place-items: center;
  }
  .xps-logo svg { width: 12px; height: 12px; }
  .xps-title { flex: 1; font-size: 12.5px; font-weight: 600; letter-spacing: .2px; }
  .xps-hbtn {
    width: 22px; height: 22px; border-radius: 6px; border: none; cursor: pointer;
    background: rgba(255,255,255,.16); color: #fff; display: grid; place-items: center;
    font-size: 12px; line-height: 1; padding: 0; transition: background .15s;
  }
  .xps-hbtn:hover { background: rgba(255,255,255,.32); }
  .xps-hbtn.on { background: #fff; color: #6366f1; }

  .xps-body { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .xps-body[hidden] { display: none !important; }

  .xps-expr { padding: 10px 11px 8px; border-bottom: 1px solid var(--xps-border); }
  .xps-row { display: flex; gap: 6px; }
  .xps-input {
    flex: 1; min-width: 0; padding: 7px 9px; font-size: 12px;
    font-family: "JetBrains Mono","Cascadia Code",Consolas,monospace;
    color: var(--xps-fg); background: var(--xps-input-bg);
    border: 1px solid var(--xps-border2); border-radius: 7px; outline: none;
  }
  .xps-input:focus { border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,.16); }

  .xps-btn {
    padding: 7px 11px; font-size: 12px; font-family: inherit; cursor: pointer;
    border: 1px solid var(--xps-border2); border-radius: 7px;
    background: var(--xps-bg); color: var(--xps-fg); white-space: nowrap; transition: .15s;
  }
  .xps-btn:hover { border-color: #6366f1; color: #6366f1; }
  .xps-btn.pri { background: linear-gradient(135deg,#6366f1,#8b5cf6); border-color: transparent; color: #fff; }
  .xps-btn.pri:hover { filter: brightness(1.08); color: #fff; }
  .xps-btn.ai { background: linear-gradient(135deg,#0ea5e9,#6366f1); border-color: transparent; color: #fff; }
  .xps-btn.ai:hover { filter: brightness(1.08); color: #fff; }
  .xps-btn.sm { padding: 4px 8px; font-size: 11px; }
  .xps-btn.block { width: 100%; }
  .xps-btn:disabled { opacity: .55; cursor: not-allowed; }

  .xps-status { margin-top: 7px; font-size: 11.5px; min-height: 0; color: var(--xps-muted); }
  .xps-status:empty { display: none; }
  .xps-status.ok { color: #10b981; }
  .xps-status.warn { color: #f59e0b; }
  .xps-status.err { color: #ef4444; }

  .xps-tabs { display: flex; padding: 0 8px; border-bottom: 1px solid var(--xps-border); background: var(--xps-bg2); }
  .xps-tab {
    flex: 1; padding: 8px 2px; font-size: 12px; font-family: inherit; cursor: pointer;
    border: none; background: transparent; color: var(--xps-muted);
    border-bottom: 2px solid transparent; transition: .15s;
  }
  .xps-tab:hover { color: var(--xps-fg); }
  .xps-tab.on { color: #6366f1; border-bottom-color: #6366f1; font-weight: 600; }

  .xps-panes { flex: 1; min-height: 0; overflow-y: auto; padding: 10px 11px; }
  .xps-pane { display: none; flex-direction: column; gap: 9px; }
  .xps-pane.on { display: flex; }

  .xps-sub { font-size: 10.5px; font-weight: 600; letter-spacing: .5px; text-transform: uppercase; color: var(--xps-muted); margin-top: 3px; }

  .xps-cand {
    display: flex; align-items: center; gap: 8px; padding: 7px 9px;
    border: 1px solid var(--xps-border); border-radius: 8px; cursor: pointer;
    background: var(--xps-bg); transition: .13s;
  }
  .xps-cand:hover { border-color: #6366f1; background: var(--xps-hover); }
  .xps-cand-main { flex: 1; min-width: 0; }
  .xps-xp {
    font-family: "JetBrains Mono","Cascadia Code",Consolas,monospace; font-size: 11.5px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--xps-fg);
  }
  .xps-meta { display: flex; gap: 6px; margin-top: 2px; font-size: 10.5px; color: var(--xps-muted); }
  .xps-warn { color: #f59e0b; }
  .xps-badge {
    flex: 0 0 auto; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 20px;
    font-family: "JetBrains Mono",Consolas,monospace; white-space: nowrap;
  }
  .xps-badge.uni { background: rgba(16,185,129,.16); color: #10b981; }
  .xps-badge.multi { background: rgba(245,158,11,.18); color: #d97706; }
  .xps-badge.bad { background: rgba(239,68,68,.16); color: #ef4444; }
  .xps-badge.stable { background: rgba(16,185,129,.16); color: #10b981; }
  .xps-badge.moderate { background: rgba(245,158,11,.18); color: #d97706; }
  .xps-badge.fragile { background: rgba(239,68,68,.14); color: #ef4444; }

  .xps-bar { flex: 0 0 auto; width: 34px; height: 4px; border-radius: 3px; background: var(--xps-border2); overflow: hidden; }
  .xps-bar i { display: block; height: 100%; border-radius: 3px; }

  .xps-empty { color: var(--xps-muted); font-size: 12px; padding: 6px 2px; }
  .xps-hint { color: var(--xps-muted); font-size: 11px; line-height: 1.6; margin: 0; }

  .xps-flash { animation: xpsFlash .6s ease; }
  @keyframes xpsFlash { 0%,100% { background: transparent; } 40% { background: rgba(99,102,241,.22); } }

  .xps-textarea {
    width: 100%; min-height: 84px; resize: vertical; padding: 7px 9px; font-size: 11.5px;
    font-family: "JetBrains Mono",Consolas,monospace; line-height: 1.6;
    color: var(--xps-fg); background: var(--xps-input-bg);
    border: 1px solid var(--xps-border2); border-radius: 7px; outline: none;
  }
  .xps-textarea:focus { border-color: #6366f1; }
  .xps-spin {
    display: inline-block; width: 10px; height: 10px; margin-right: 5px; vertical-align: -1px;
    border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%;
    animation: xpsSpin .7s linear infinite;
  }
  @keyframes xpsSpin { to { transform: rotate(360deg); } }

  /* 拾取器 & 高亮层 */
  .xps-pick, .xps-hl {
    position: absolute; pointer-events: none; border-radius: 3px;
    box-shadow: 0 0 0 1px rgba(255,255,255,.7);
  }
  .xps-pick {
    background: rgba(99,102,241,.30); outline: 2px solid #6366f1;
    box-shadow: 0 0 0 1px rgba(255,255,255,.85), 0 0 22px rgba(99,102,241,.55);
  }
  .xps-pick-size {
    position: absolute; top: -17px; right: 0; padding: 0 6px; height: 15px; line-height: 15px;
    font-family: Consolas,monospace; font-size: 10px; border-radius: 3px;
    background: #6366f1; color: #fff; white-space: nowrap;
  }
  .xps-hl { background: rgba(16,185,129,.20); outline: 1px solid #10b981; }
  .xps-hl.primary { background: rgba(99,102,241,.26); outline: 2px solid #6366f1; }
  .xps-hl-tag {
    position: absolute; top: -16px; left: 0; padding: 0 5px; height: 15px; line-height: 15px;
    font-family: Consolas,monospace; font-size: 10px; border-radius: 3px;
    background: #10b981; color: #fff; white-space: nowrap;
  }
  .xps-hl.primary .xps-hl-tag { background: #6366f1; }
  .xps-tip {
    position: absolute; padding: 5px 9px; border-radius: 6px; font-size: 11px;
    font-family: Consolas,monospace; background: #1f2430; color: #fff;
    white-space: nowrap; max-width: 460px; overflow: hidden; text-overflow: ellipsis;
    box-shadow: 0 4px 16px rgba(0,0,0,.3);
  }
  .xps-tip b { color: #a5b4fc; font-weight: 600; }
  .xps-tip i { color: #7dd3a0; font-style: normal; }

  .xps-mask {
    position: absolute; inset: 0; background: rgba(99,102,241,.06); pointer-events: none;
    outline: 2px dashed #6366f1; outline-offset: -2px;
  }

  `;

  var state = {
    host: null,
    shadow: null,
    panel: null,
    visible: false,
    collapsed: false,
    pos: null,
    handlers: {},
    theme: "light",
    bridge: "http://127.0.0.1:8790",
    startHidden: false
  };

  function h(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function scoreClass(score) {
    return score >= 70 ? "stable" : score >= 45 ? "moderate" : "fragile";
  }

  function makeBar(score) {
    var bar = h("div", "xps-bar");
    var i = h("i");
    i.style.width = Math.max(4, score) + "%";
    i.style.background = score >= 70 ? "#10b981" : score >= 45 ? "#f59e0b" : "#ef4444";
    bar.appendChild(i);
    return bar;
  }

  function makeBadge(text, cls) {
    return h("span", "xps-badge " + cls, text);
  }

  function countBadge(n) {
    return makeBadge(n === 1 ? "唯一" : n + " 个", n === 1 ? "uni" : "multi");
  }

  /* ---------------- 构建 DOM ---------------- */
  function build() {
    if (state.host) return;

    var host = document.createElement("div");
    host.id = HOST_ID;
    host.setAttribute("data-xps", "1");
    host.style.cssText =
      "position:fixed;top:0;left:0;right:0;bottom:0;pointer-events:none;" +
      "z-index:2147483647;";

    var shadow = host.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = STYLE;
    shadow.appendChild(style);

    var panel = h("div", "xps");
    panel.setAttribute("data-xps-ui", "1");
    panel.innerHTML = [
      '<div class="xps-head" data-role="head">',
      '  <div class="xps-logo"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><circle cx="12" cy="12" r="7"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg></div>',
      '  <div class="xps-title">XPath Studio</div>',
      '  <button class="xps-hbtn" data-role="pick" title="拾取元素（Alt+Shift+P）">◎</button>',
      '  <button class="xps-hbtn" data-role="theme" title="切换主题">◐</button>',
      '  <button class="xps-hbtn" data-role="fold" title="折叠">–</button>',
      '  <button class="xps-hbtn" data-role="close" title="关闭">✕</button>',
      "</div>",
      '<div class="xps-body" data-role="body">',
      '  <div class="xps-expr">',
      '    <div class="xps-row">',
      '      <input class="xps-input" data-role="xpath" placeholder="//button[@id=\'submit\']" spellcheck="false" />',
      '      <button class="xps-btn pri" data-role="validate">校验</button>',
      "    </div>",
      '    <div class="xps-status" data-role="status"></div>',
      "  </div>",
      '  <div class="xps-tabs">',
      '    <button class="xps-tab on" data-tab="cand">定位器</button>',
      '    <button class="xps-tab" data-tab="match">匹配</button>',
      '    <button class="xps-tab" data-tab="scan">扫描</button>',
      '    <button class="xps-tab" data-tab="ai">AI</button>',
      "  </div>",
      '  <div class="xps-panes">',
      '    <div class="xps-pane on" data-pane="cand">',
      '      <div data-role="candList"></div>',
      "    </div>",
      '    <div class="xps-pane" data-pane="match">',
      '      <div class="xps-sub">匹配节点</div>',
      '      <div data-role="matchList"></div>',
      "    </div>",
      '    <div class="xps-pane" data-pane="scan">',
      '      <p class="xps-hint">扫描当前页面所有可交互元素，给出最稳健的定位器。</p>',
      '      <div class="xps-row"><button class="xps-btn pri block" data-role="scan">开始扫描</button></div>',
      '      <div data-role="scanList"></div>',
      "    </div>",
      '    <div class="xps-pane" data-pane="ai">',
      '      <p class="xps-hint">描述要定位的元素，由本地桌面版 XPath Studio 调用大模型生成（需桌面版正在运行）。</p>',
      '      <div class="xps-row">',
      '        <input class="xps-input" data-role="bridge" placeholder="http://127.0.0.1:8790" spellcheck="false" />',
      '        <button class="xps-btn sm" data-role="bridgeTest">测试</button>',
      '      </div>',
      '      <div class="xps-row">',
      '        <input class="xps-input" data-role="aiInput" placeholder="如：右上角带角标的购物车图标" />',
      '      </div>',
      '      <div class="xps-row"><button class="xps-btn ai block" data-role="aiGo">AI 生成</button></div>',
      '      <div class="xps-status" data-role="aiStatus"></div>',
      '      <div data-role="aiList"></div>',
      "    </div>",
      "  </div>",
      "</div>"
    ].join("");

    shadow.appendChild(panel);

    state.host = host;
    state.shadow = shadow;
    state.panel = panel;

    bindEvents();
    applyTheme();
    restorePos();
  }

  function q(role) {
    return state.panel.querySelector('[data-role="' + role + '"]');
  }

  function bindEvents() {
    var panel = state.panel;

    q("close").addEventListener("click", function () {
      if (state.handlers.onClose) state.handlers.onClose();
      else api.hide();
    });
    q("fold").addEventListener("click", function () { api.toggleFold(); });
    q("theme").addEventListener("click", function () {
      state.theme = state.theme === "light" ? "dark" : "light";
      applyTheme();
      saveSettings({ theme: state.theme });
    });
    q("pick").addEventListener("click", function () {
      if (state.handlers.onPickToggle) state.handlers.onPickToggle();
    });
    q("validate").addEventListener("click", function () {
      if (state.handlers.onValidate) state.handlers.onValidate(q("xpath").value);
    });
    q("xpath").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && state.handlers.onValidate) state.handlers.onValidate(q("xpath").value);
    });
    q("scan").addEventListener("click", function () {
      if (state.handlers.onScan) state.handlers.onScan();
    });
    q("aiGo").addEventListener("click", function () {
      var v = q("aiInput").value.trim();
      if (v && state.handlers.onAi) state.handlers.onAi(v);
    });
    q("aiInput").addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var v = q("aiInput").value.trim();
        if (v && state.handlers.onAi) state.handlers.onAi(v);
      }
    });
    q("bridgeTest").addEventListener("click", function () {
      if (state.handlers.onBridgeTest) state.handlers.onBridgeTest(q("bridge").value.trim());
    });
    q("bridge").addEventListener("change", function () {
      saveSettings({ bridge: q("bridge").value.trim() });
    });

    panel.querySelectorAll(".xps-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        panel.querySelectorAll(".xps-tab").forEach(function (t) { t.classList.remove("on"); });
        tab.classList.add("on");
        panel.querySelectorAll(".xps-pane").forEach(function (p) {
          p.classList.toggle("on", p.getAttribute("data-pane") === tab.getAttribute("data-tab"));
        });
      });
    });

    makeDraggable(panel.querySelector('[data-role="head"]'), panel);
  }

  function makeDraggable(handle, panel) {
    var start = null;
    handle.addEventListener("mousedown", function (e) {
      if (e.target.closest(".xps-hbtn")) return;
      var rect = panel.getBoundingClientRect();
      start = { x: e.clientX, y: e.clientY, left: rect.left, top: rect.top };
      e.preventDefault();
    });
    document.addEventListener("mousemove", function (e) {
      if (!start) return;
      var left = start.left + (e.clientX - start.x);
      var top = start.top + (e.clientY - start.y);
      left = Math.max(4, Math.min(window.innerWidth - 60, left));
      top = Math.max(4, Math.min(window.innerHeight - 40, top));
      panel.style.left = left + "px";
      panel.style.top = top + "px";
      panel.style.right = "auto";
      panel.style.bottom = "auto";
    });
    document.addEventListener("mouseup", function () {
      if (!start) return;
      start = null;
      var rect = panel.getBoundingClientRect();
      state.pos = { left: rect.left, top: rect.top };
      saveSettings({ pos: state.pos });
    });
  }

  function restorePos() {
    if (state.pos) {
      state.panel.style.left = state.pos.left + "px";
      state.panel.style.top = state.pos.top + "px";
    } else {
      state.panel.style.right = "18px";
      state.panel.style.top = "18px";
    }
  }

  function applyTheme() {
    var dark = state.theme === "dark";
    var p = state.panel;
    p.style.setProperty("--xps-bg", dark ? "#14171f" : "#ffffff");
    p.style.setProperty("--xps-bg2", dark ? "#1a1e28" : "#f7f8fc");
    p.style.setProperty("--xps-fg", dark ? "#e8ebf2" : "#1c2130");
    p.style.setProperty("--xps-muted", dark ? "#7b8497" : "#8b93a7");
    p.style.setProperty("--xps-border", dark ? "#262b38" : "#e4e7f0");
    p.style.setProperty("--xps-border2", dark ? "#333a4b" : "#d3d8e6");
    p.style.setProperty("--xps-input-bg", dark ? "#10131a" : "#f6f7fb");
    p.style.setProperty("--xps-hover", dark ? "#1e2330" : "#f1f3fa");
  }

  function saveSettings(obj) {
    try {
      chrome.storage.local.get(["xpsSettings"], function (r) {
        var s = (r && r.xpsSettings) || {};
        Object.assign(s, obj);
        chrome.storage.local.set({ xpsSettings: s });
      });
    } catch (e) { /* 忽略 */ }
  }

  function loadSettings(cb) {
    try {
      chrome.storage.local.get(["xpsSettings"], function (r) {
        var s = (r && r.xpsSettings) || {};
        if (s.pos) state.pos = s.pos;
        if (s.theme) state.theme = s.theme;
        if (s.bridge) state.bridge = s.bridge;
        if (s.collapsed) state.collapsed = true;
        cb && cb();
      });
    } catch (e) { cb && cb(); }
  }

  /* ---------------- 渲染 ---------------- */
  function setStatus(text, cls) {
    var el = q("status");
    el.className = "xps-status" + (cls ? " " + cls : "");
    el.innerHTML = text || "";
  }

  function renderGen(res) {
    var box = q("candList");
    box.innerHTML = "";
    if (!res || !res.xpath || !res.xpath.length) {
      box.appendChild(h("div", "xps-empty", "点击页面元素或输入 XPath 以生成候选定位器。"));
      return;
    }

    var t = res.target || {};
    var head = h("div", "xps-sub", "目标 <" + t.tag + "> " + (t.dynamicId ? "⚠ 动态ID" : ""));
    box.appendChild(head);

    res.xpath.forEach(function (c) {
      var item = h("div", "xps-cand");
      item.appendChild(makeBar(c.score));
      var main = h("div", "xps-cand-main");
      main.appendChild(h("div", "xps-xp", c.xpath));
      var meta = h("div", "xps-meta");
      meta.appendChild(h("span", null, c.label + (c.note ? " · " + c.note : "")));
      if (c.warn) meta.appendChild(h("span", "xps-warn", "⚠ " + c.warn));
      main.appendChild(meta);
      item.appendChild(main);
      item.appendChild(countBadge(c.count));
      item.appendChild(makeBadge(c.score + " " + c.level, scoreClass(c.score)));
      item.addEventListener("click", function () {
        q("xpath").value = c.xpath;
        if (state.handlers.onValidate) state.handlers.onValidate(c.xpath, true);
      });
      box.appendChild(item);
    });

    if (res.css && res.css.css) {
      box.appendChild(h("div", "xps-sub", "CSS 选择器"));
      var ci = h("div", "xps-cand");
      ci.appendChild(makeBar(res.css.score));
      var cm = h("div", "xps-cand-main");
      cm.appendChild(h("div", "xps-xp", res.css.css));
      cm.appendChild(h("div", "xps-meta", "点击复制"));
      ci.appendChild(cm);
      if (res.css.count != null) ci.appendChild(countBadge(res.css.count));
      ci.appendChild(makeBadge(res.css.score + " " + res.css.level, scoreClass(res.css.score)));
      ci.addEventListener("click", function () { copy(res.css.css); });
      box.appendChild(ci);
    }

    if (res.playwright && res.playwright.length) {
      box.appendChild(h("div", "xps-sub", "Playwright 定位器"));
      res.playwright.forEach(function (p) {
        var pi = h("div", "xps-cand");
        pi.appendChild(makeBar(p.score));
        var pm = h("div", "xps-cand-main");
        pm.appendChild(h("div", "xps-xp", "page." + p.code));
        pm.appendChild(h("div", "xps-meta", "点击复制"));
        pi.appendChild(pm);
        pi.appendChild(makeBadge(p.score + (p.score >= 70 ? " 稳定" : " 一般"), p.score >= 70 ? "stable" : "moderate"));
        pi.addEventListener("click", function () { copy(p.code); });
        box.appendChild(pi);
      });
    }
  }

  function renderMatches(matches, onPick) {
    var box = q("matchList");
    box.innerHTML = "";
    if (!matches || !matches.length) {
      box.appendChild(h("div", "xps-empty", "没有匹配到节点。"));
      return;
    }
    matches.slice(0, 200).forEach(function (m, i) {
      var item = h("div", "xps-cand");
      if (m.kind !== "node") {
        item.appendChild(makeBadge("值", "multi"));
        var b0 = h("div", "xps-cand-main");
        b0.appendChild(h("div", "xps-xp", m.value));
        item.appendChild(b0);
        box.appendChild(item);
        return;
      }
      item.appendChild(makeBadge("#" + i, "uni"));
      var b = h("div", "xps-cand-main");
      b.appendChild(h("div", "xps-xp", "<" + m.tag + ">"));
      var preview = Object.keys(m.attrs || {}).map(function (k) { return k + '="' + m.attrs[k] + '"'; }).join(" ");
      b.appendChild(h("div", "xps-meta", (preview + " " + (m.text || "")).trim().slice(0, 90) || "(无属性)"));
      item.appendChild(b);
      item.addEventListener("click", function () { onPick && onPick(m.node); });
      box.appendChild(item);
    });
  }

  function renderScan(items, onPick) {
    var box = q("scanList");
    box.innerHTML = "";
    if (!items || !items.length) {
      box.appendChild(h("div", "xps-empty", "点击「开始扫描」查找页面可交互元素。"));
      return;
    }
    var head = h("div", "xps-sub", "共 " + items.length + " 个 · 点击定位，双击复制");
    box.appendChild(head);
    items.forEach(function (it) {
      var item = h("div", "xps-cand");
      item.appendChild(makeBar(it.score));
      var b = h("div", "xps-cand-main");
      b.appendChild(h("div", "xps-xp", it.xpath));
      b.appendChild(h("div", "xps-meta", [it.tag, it.text].filter(Boolean).join(" · ")));
      item.appendChild(b);
      item.appendChild(makeBadge(it.score + " " + it.level, scoreClass(it.score)));
      item.addEventListener("click", function () {
        q("xpath").value = it.xpath;
        if (state.handlers.onValidate) state.handlers.onValidate(it.xpath, true);
        onPick && onPick(it.node);
      });
      item.addEventListener("dblclick", function () { copy(it.xpath); });
      box.appendChild(item);
    });
  }

  function renderAiList(list) {
    var box = q("aiList");
    box.innerHTML = "";
    list.forEach(function (xp, i) {
      var item = h("div", "xps-cand");
      var b = h("div", "xps-cand-main");
      b.appendChild(h("div", "xps-xp", xp));
      b.appendChild(h("div", "xps-meta", i === 0 ? "AI 推荐" : "备选 " + i));
      item.appendChild(b);
      item.appendChild(makeBadge("使用", "uni"));
      item.addEventListener("click", function () {
        q("xpath").value = xp;
        if (state.handlers.onValidate) state.handlers.onValidate(xp, true);
      });
      box.appendChild(item);
    });
  }

  function setAiStatus(text, cls) {
    var el = q("aiStatus");
    el.className = "xps-status" + (cls ? " " + cls : "");
    el.innerHTML = text || "";
  }

  function setPicking(on) {
    var btn = q("pick");
    if (btn) btn.classList.toggle("on", !!on);
  }

  function copy(text) {
    try {
      navigator.clipboard.writeText(text).then(function () {
        if (state.handlers.onToast) state.handlers.onToast("已复制");
      }, function () { fallbackCopy(text); });
    } catch (e) {
      fallbackCopy(text);
    }
  }

  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;left:-9999px;";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* 忽略 */ }
    document.body.removeChild(ta);
    if (state.handlers.onToast) state.handlers.onToast("已复制");
  }

  /* ---------------- 对外 API ---------------- */
  var api = {
    mount: function (handlers, opts) {
      state.handlers = handlers || {};
      // opts.hidden=true：只挂载不显示（桌面版「抓取元素」驱动时用，页面上不弹面板）
      state.startHidden = !!(opts && opts.hidden);
      loadSettings(function () {
        build();
        if (!state.host.parentNode) {
          (document.documentElement || document.body).appendChild(state.host);
        }
        if (q("bridge")) q("bridge").value = state.bridge;
        if (state.collapsed) api.toggleFold(true);
        if (state.startHidden) api.hide();
      });
    },
    show: function () {
      build();
      if (!state.host.parentNode) (document.documentElement || document.body).appendChild(state.host);
      state.panel.hidden = false;
      state.visible = true;
    },
    hide: function () {
      if (state.panel) state.panel.hidden = true;
      state.visible = false;
    },
    toggle: function () {
      if (state.visible) api.hide(); else api.show();
    },
    isVisible: function () { return state.visible; },
    toggleFold: function (force) {
      var body = q("body");
      var fold = state.collapsed;
      if (typeof force === "boolean") fold = !force;
      state.collapsed = !fold;
      body.hidden = state.collapsed;
      q("fold").textContent = state.collapsed ? "+" : "–";
      saveSettings({ collapsed: state.collapsed });
    },
    setStatus: setStatus,
    renderGen: renderGen,
    renderMatches: renderMatches,
    renderScan: renderScan,
    renderAiList: renderAiList,
    setAiStatus: setAiStatus,
    setPicking: setPicking,
    setXPath: function (v) { q("xpath").value = v; },
    getXPath: function () { return q("xpath").value; },
    selectTab: function (name) {
      state.panel.querySelectorAll(".xps-tab").forEach(function (t) {
        t.classList.toggle("on", t.getAttribute("data-tab") === name);
      });
      state.panel.querySelectorAll(".xps-pane").forEach(function (p) {
        p.classList.toggle("on", p.getAttribute("data-pane") === name);
      });
    },
    copy: copy,
    getHost: function () { return state.host; },
    getBridge: function () {
      var el = q("bridge");
      return (el && el.value.trim()) || state.bridge;
    },
    setBridge: function (v) {
      state.bridge = v;
      if (q("bridge")) q("bridge").value = v;
      saveSettings({ bridge: v });
    }
  };

  global.XPathStudioPanel = api;
})(typeof window !== "undefined" ? window : globalThis);
