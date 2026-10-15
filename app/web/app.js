/* XPath Studio：浏览器抓取与实时 XPath 工作台。 */
(() => {
  "use strict";
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const state = { config: loadConfig() };
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  async function api(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  let toastTimer = null;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 2200);
  }

  function loadConfig() {
    try {
      return JSON.parse(localStorage.getItem("xpath-studio-config") || "{}");
    } catch {
      return {};
    }
  }

  /* ---------------------- 主题 ---------------------- */
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    $("#themeLabel").textContent = theme === "light" ? "深色" : "浅色";
    localStorage.setItem("xpath-studio-theme", theme);
  }
  $("#btnTheme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    applyTheme(cur === "light" ? "dark" : "light");
  });
  applyTheme(localStorage.getItem("xpath-studio-theme") || "light");

  function scoreEl(score, level) {
    const cls = score >= 70 ? "stable" : score >= 45 ? "moderate" : "fragile";
    return el("span", "badge " + cls, score + " " + level);
  }
  function scoreBar(score) {
    const bar = el("div", "score-bar");
    const i = el("i", score >= 70 ? "s-ok" : score >= 45 ? "s-mid" : "s-low");
    i.style.width = Math.max(4, score) + "%";
    bar.appendChild(i);
    return bar;
  }
  function countBadge(n) {
    const cls = n === 1 ? "uni" : n < 0 ? "bad" : "multi";
    return el("span", "badge " + cls, n < 0 ? "错误" : n === 1 ? "唯一" : n + " 个");
  }

  /* ---------------------- 查询历史 ---------------------- */
  const HISTORY_KEY = "xpath-studio-history";
  function pushHistory(xp) {
    if (!xp) return;
    let h = [];
    try { h = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch { /* ignore */ }
    h = [xp, ...h.filter((x) => x !== xp)].slice(0, 12);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h));
    renderHistory();
  }
  function renderHistory() {
    const row = $("#historyRow");
    row.innerHTML = "";
    let h = [];
    try { h = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch { /* ignore */ }
    h.forEach((xp) => {
      const chip = el("button", "history-chip", xp);
      chip.title = xp;
      chip.addEventListener("click", () => { $("#xpathInput").value = xp; validate(xp); });
      row.appendChild(chip);
    });
  }


  // 校验使用浏览器实时 DOM，不解析或缓存 HTML 快照。
  let validationId = 0;
  let commandQueue = Promise.resolve();
  function resetMatches() {
    $("#matchCount").textContent = "—";
    $("#matchList").textContent = "校验后，浏览器匹配元素会同步高亮。";
  }
  function browserCommand(action, xpath, id) {
    const target = lastPick && lastPick.frame && Object.assign({}, lastPick.frame, {
      browserId: lastPick.browserId,
    });
    const task = commandQueue.catch(() => {}).then(() => {
      // 丢弃尚未发送的旧查询；串行投递，防止慢请求覆盖后续高亮或清空。
      if (id !== validationId) return null;
      return api("/api/bridge/validate", { target, action, xpath });
    });
    commandQueue = task;
    return task;
  }
  async function validate(xpath, record) {
    const xp = (xpath || $("#xpathInput").value).trim();
    if (!lastPick) return toast("请先在浏览器中抓取元素");
    if (librarySelection && !libraryScopeMatches(librarySelection))
      return toast("元素库记录来自其他页面或框架，请先在对应页面重新抓取");
    if (!xp) return toast("请输入 XPath");
    $("#xpathInput").value = xp;
    const id = ++validationId;
    const msg = $("#validateMsg");
    msg.className = "msg loading";
    msg.textContent = "正在浏览器中校验并高亮…";
    resetMatches();
    try {
      const result = await browserCommand("validate", xp, id);
      if (!result || id !== validationId) return;
      if (!result.ok) throw new Error(result.error || "浏览器未确认校验结果");
      if (record) pushHistory(xp);
      if (!result.valid) {
        msg.className = "msg err";
        msg.textContent = "表达式无效：" + result.error;
        $("#matchCount").textContent = "0";
        return;
      }
      const n = result.count;
      msg.className = "msg " + (n === 1 ? "ok" : "warn");
      msg.textContent = n === 0 ? "没有匹配元素，已清除浏览器高亮" :
        result.highlighted ? "匹配 " + n + " 个节点 · 浏览器已同步高亮" +
          (result.truncated ? "（最多展示 500 个）" : "") : "表达式有效 · 返回值，无元素可高亮";
      $("#matchCount").textContent = String(n);
      const list = $("#matchList");
      list.innerHTML = "";
      (result.matches || []).forEach((m, index) => {
        const item = el("div", "match-item");
        if (m.kind === "value") item.appendChild(el("code", "mono", m.value));
        else {
          const attrs = m.attrs || {};
          item.appendChild(el("div", "match-title mono", (index + 1) + " <" + m.tag +
            (attrs.id ? "#" + attrs.id : "") + ">"));
          if (m.text) item.appendChild(el("div", "muted small", m.text));
        }
        list.appendChild(item);
      });
      if (!n) list.textContent = "当前来源网页中没有匹配元素。";
    } catch (e) {
      if (id !== validationId) return;
      msg.className = "msg err";
      msg.textContent = e.message;
    }
  }
  $("#btnValidate").addEventListener("click", () => validate(null, true));
  $("#xpathInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); validate(null, true); }
  });
  $("#xpathInput").addEventListener("input", () => {
    validationId++;
    resetMatches();
    $("#validateMsg").className = "msg";
    $("#validateMsg").textContent = "表达式已修改，点击校验更新浏览器高亮";
  });
  $("#btnCopy").addEventListener("click", () => {
    const value = $("#xpathInput").value.trim();
    if (value) copyText(value, "已复制 XPath");
  });
  $("#btnClear").addEventListener("click", async () => {
    const id = ++validationId;
    $("#xpathInput").value = "";
    resetMatches();
    $("#validateMsg").className = "msg";
    $("#validateMsg").textContent = "";
    if (!lastPick) return;
    try {
      const result = await browserCommand("clear", "", id);
      if (!result || id !== validationId) return;
      $("#validateMsg").className = "msg " + (result.ok ? "ok" : "err");
      $("#validateMsg").textContent = result.ok ? "浏览器高亮已清除" : result.error;
    } catch (e) {
      if (id === validationId) $("#validateMsg").textContent = "清除高亮失败：" + e.message;
    }
  });
  /* ---------------------- 设置弹窗 ---------------------- */
  const PRESETS = {
    deepseek: { baseUrl: "https://api.deepseek.com", model: "deepseek-chat" },
    openai: { baseUrl: "https://api.openai.com", model: "gpt-4o-mini" },
    qwen: { baseUrl: "https://dashscope.aliyuncs.com/compatible-mode", model: "qwen-plus" },
    moonshot: { baseUrl: "https://api.moonshot.cn", model: "moonshot-v1-8k" },
    ollama: { baseUrl: "http://localhost:11434", model: "llama3.1" },
  };

  function openSettings() {
    const cfg = loadConfig();
    $("#cfgBaseUrl").value = cfg.baseUrl || "";
    $("#cfgApiKey").value = cfg.apiKey || "";
    $("#cfgModel").value = cfg.model || "";
    $("#testMsg").textContent = "";
    $("#testMsg").className = "msg";
    $("#settingsModal").hidden = false;
  }

  $("#btnSettings").addEventListener("click", openSettings);
  $("#btnCloseSettings").addEventListener("click", () => ($("#settingsModal").hidden = true));
  $("#settingsModal").addEventListener("click", (e) => {
    if (e.target === $("#settingsModal")) $("#settingsModal").hidden = true;
  });

  $$("#presetRow .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const p = PRESETS[chip.dataset.preset];
      if (!p) return;
      $("#cfgBaseUrl").value = p.baseUrl;
      $("#cfgModel").value = p.model;
      if (chip.dataset.preset === "ollama") $("#cfgApiKey").value = $("#cfgApiKey").value || "ollama";
    });
  });

  $("#btnSaveSettings").addEventListener("click", async () => {
    const cfg = {
      baseUrl: $("#cfgBaseUrl").value.trim(),
      apiKey: $("#cfgApiKey").value.trim(),
      model: $("#cfgModel").value.trim(),
    };
    localStorage.setItem("xpath-studio-config", JSON.stringify(cfg));
    state.config = cfg;
    $("#settingsModal").hidden = true;
    // 同时写入本地服务端配置，浏览器扩展桥接时可直接复用
    try {
      await api("/api/config", { config: cfg });
      toast("设置已保存（浏览器扩展可复用）");
    } catch {
      toast("设置已保存");
    }
  });

  $("#btnTestConn").addEventListener("click", async () => {
    const cfg = {
      baseUrl: $("#cfgBaseUrl").value.trim(),
      apiKey: $("#cfgApiKey").value.trim(),
      model: $("#cfgModel").value.trim(),
    };
    const msg = $("#testMsg");
    msg.className = "msg loading";
    msg.innerHTML = '<span class="spin"></span>测试中…';
    try {
      const res = await api("/api/ai/test", { config: cfg });
      if (res.ok) { msg.className = "msg ok"; msg.textContent = "✓ 连接成功，模型回复：" + res.reply; }
      else { msg.className = "msg err"; msg.textContent = "✕ " + res.error; }
    } catch (e) {
      msg.className = "msg err";
      msg.textContent = "请求失败：" + e.message;
    }
  });

  const bridge = { ws: null, retry: 0, timer: null, connected: false, ext: false };
  let lastPick = null;
  let librarySelection = null;
  function libraryScopeMatches(record) {
    const frame = lastPick && lastPick.frame || {};
    if (record.url && record.url !== (frame.url || lastPick && lastPick.url)) return false;
    if (record.frame) {
      for (const key of ["isTop", "frameId", "topUrl"])
        if (record.frame[key] != null && record.frame[key] !== frame[key]) return false;
    }
    return true;
  }
  window.XPSWorkbench = {
    getCurrent() {
      return { xpath: $("#xpathInput").value.trim(),
        frame: lastPick && lastPick.frame || null,
        url: lastPick && (lastPick.frame && lastPick.frame.url || lastPick.url) || "",
        name: lastPick && (lastPick.text || lastPick.id || lastPick.tag) || "" };
    },
    useElement(record) {
      librarySelection = record;
      validationId++;
      $("#xpathInput").value = record.xpath;
      resetMatches();
      $("#validateMsg").className = "msg";
      $("#validateMsg").textContent = "已载入「" + record.name + "」。在对应页面抓取后可校验。";
      $("#xpathInput").focus();
    }
  };

  function bridgeWsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/ws`;
  }

  function setBridgeState(connected, ext) {
    const chip = $("#bridgeChip");
    const text = $("#bridgeChipText");
    const dot = $("#grabDot");
    if (!chip) return;
    bridge.connected = connected;
    bridge.ext = ext;
    chip.classList.toggle("on", !!ext);
    chip.classList.toggle("off", !!connected && !ext);
    text.textContent = ext ? "扩展已连接" : connected ? "等待扩展…" : "服务未连接";
    if (dot) dot.classList.toggle("on", !!ext);
    // 没连上扩展时，在抓取面板里给一个显眼的安装入口
    const callout = $("#grabInstall");
    if (callout) callout.hidden = !!ext;
  }

  function connectBridge() {
    let ws;
    try { ws = new WebSocket(bridgeWsUrl()); }
    catch { scheduleBridgeReconnect(); return; }
    bridge.ws = ws;

    ws.onopen = () => {
      bridge.retry = 0;
      ws.send(JSON.stringify({ type: "hello", role: "ui", version: "1.0" }));
      setBridgeState(true, bridge.ext);
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      handleBridgeMessage(msg);
    };
    ws.onclose = () => {
      bridge.ws = null;
      setBridgeState(false, false);
      scheduleBridgeReconnect();
    };
    ws.onerror = () => { /* onclose 紧随其后 */ };
  }

  function scheduleBridgeReconnect() {
    if (bridge.timer) return;
    const delay = Math.min(15000, 1200 + bridge.retry * 1500);
    bridge.retry++;
    bridge.timer = setTimeout(() => { bridge.timer = null; connectBridge(); }, delay);
  }

  function handleBridgeMessage(msg) {
    if (!msg || !msg.type) return;
    if (msg.type === "stats" && msg.stats) {
      setBridgeState(true, (msg.stats.extensions || 0) > 0);
      return;
    }
    if (msg.type === "picked") { renderPick(msg.payload || {}); return; }
    if (msg.type === "status") {
      const p = msg.payload || {};
      if (p.kind === "start-pick" && p.ok === false) {
        $("#grabMsg").className = "msg err";
        $("#grabMsg").textContent = "✕ " + (p.error || "扩展无法在当前页面拾取");
        $("#btnGrab").classList.remove("armed");
      } else if (p.kind === "start-pick" && p.ok && p.skippedFrames) {
        $("#grabMsg").className = "msg warn";
        $("#grabMsg").textContent = "已启动抓取；" + p.skippedFrames + " 个框架因权限或加载状态未启用。Ctrl＋左键锁定后确认。";
      } else if (p.kind === "cancel") {
        $("#grabMsg").className = "msg warn";
        $("#grabMsg").textContent = "已在浏览器中取消抓取";
        $("#btnGrab").classList.remove("armed");
      }
      return;
    }
  }

  async function startGrab() {
    const btn = $("#btnGrab");
    $("#grabMsg").className = "msg loading";
    $("#grabMsg").innerHTML = '<span class="spin"></span>正在通知浏览器扩展…';
    try {
      const res = await api("/api/bridge/pick", {});
      if (!res.ok) {
        $("#grabMsg").className = "msg err";
        $("#grabMsg").textContent = "✕ " + (res.error || "无法通知扩展");
        toast("没有已连接的浏览器扩展");
        return;
      }
      $("#grabMsg").className = "msg ok";
      $("#grabMsg").innerHTML =
        '已通知扩展。请切到浏览器：悬停高亮，<kbd>↑ / ↓</kbd> 切换父子元素，<kbd>Ctrl</kbd>＋左键锁定，确认后回传。';
      btn.classList.add("armed");
      setTimeout(() => btn.classList.remove("armed"), 15000);
      toast("已进入抓取模式，请到浏览器操作");
    } catch (e) {
      $("#grabMsg").className = "msg err";
      $("#grabMsg").textContent = "请求失败：" + e.message;
    }
  }

  function renderPick(p) {
    lastPick = p;
    librarySelection = null;
    validationId++;
    resetMatches();
    $("#validateMsg").textContent = "点击校验，在来源网页中高亮匹配元素";
    $("#validateMsg").className = "msg";
    $("#targetContext").textContent = (p.title || p.url || "已抓取元素") +
      (p.frame && !p.frame.isTop ? " · iframe" : " · 当前网页");
    $("#btnGrab").classList.remove("armed");
    const msg = $("#grabMsg");
    msg.className = "msg ok";
    msg.innerHTML = "✓ 已从浏览器抓取到元素" +
      (p.matchCount >= 0 ? `（抓取时匹配 ${p.matchCount} 个节点）` : "");

    const body = $("#grabBody");
    body.innerHTML = "";

    // 目标摘要
    const card = el("div", "grab-target");
    card.appendChild(el("div", "grab-thumb", "<" + (p.tag || "?") + ">"));
    const meta = el("div", "grab-meta");
    const head = "<" + (p.tag || "?") + (p.id ? "#" + p.id : "") +
      ((p.classes || []).length ? "." + p.classes.slice(0, 2).join(".") : "") + ">";
    meta.appendChild(el("div", "grab-title", head));
    meta.appendChild(el("div", "grab-sub", [p.title, p.url].filter(Boolean).join("  ·  ")));
    card.appendChild(meta);
    if (p.target && p.target.score != null) card.appendChild(scoreEl(p.target.score, p.target.level || ""));
    body.appendChild(card);

    const inFrame = p.frame && !p.frame.isTop;
    if (inFrame) {
      const scope = el("div", "msg warn");
      scope.textContent = "来自 iframe #" + p.frame.frameId + "：" + (p.frame.url || p.url || "") +
        "。以下 XPath / CSS / Playwright 仅在该框架内有效；自动化时须先切换到对应框架，不能直接使用 page 定位。";
      body.appendChild(scope);
      body.appendChild(el("div", "grab-sub", "顶层网页：" + (p.frame.topUrl || "未知")));
    }

    if (p.text) {
      const t = el("div", "grab-sub");
      t.textContent = "文本：" + p.text;
      body.appendChild(t);
    }

    // 候选定位器
    const cands = (p.candidates || []).filter((c) => c && c.xpath);
    if (cands.length) {
      body.appendChild(el("div", "sub-head", "候选定位器"));
      const list = el("div", "cand-list");
      cands.forEach((c) => {
        const item = el("div", "cand");
        item.appendChild(scoreBar(c.score));
        const main = el("div", "cand-main");
        main.appendChild(el("div", "cand-xpath", c.xpath));
        const m = el("div", "cand-meta");
        m.appendChild(el("span", "cand-label", c.label + (c.note ? " · " + c.note : "")));
        if (c.warn) m.appendChild(el("span", "cand-note", "⚠ " + c.warn));
        main.appendChild(m);
        item.appendChild(main);
        item.appendChild(countBadge(c.count));
        item.appendChild(scoreEl(c.score, c.level));
        item.addEventListener("click", () => {
          $("#xpathInput").value = c.xpath;
          pushHistory(c.xpath);
          validate(c.xpath, true);
        });
        list.appendChild(item);
      });
      body.appendChild(list);
    }

    // CSS 选择器
    if (p.css && p.css.css) {
      body.appendChild(el("div", "sub-head", "CSS 选择器"));
      const list = el("div", "cand-list");
      const item = el("div", "cand");
      item.appendChild(scoreBar(p.css.score));
      const main = el("div", "cand-main");
      main.appendChild(el("div", "cand-xpath", p.css.css));
      main.appendChild(el("div", "cand-meta", "点击复制"));
      item.appendChild(main);
      item.appendChild(scoreEl(p.css.score, p.css.level));
      item.addEventListener("click", () =>
        navigator.clipboard.writeText(p.css.css).then(() => toast("已复制 CSS"), () => { /* 忽略 */ }));
      list.appendChild(item);
      body.appendChild(list);
    }

    // Playwright
    if ((p.playwright || []).length) {
      body.appendChild(el("div", "sub-head", "Playwright 定位器"));
      const list = el("div", "cand-list");
      p.playwright.forEach((pw) => {
        const item = el("div", "cand");
        item.appendChild(scoreBar(pw.score));
        const main = el("div", "cand-main");
        main.appendChild(el("div", "cand-xpath", (inFrame ? "frame." : "page.") + pw.code));
        main.appendChild(el("div", "cand-meta", "点击复制"));
        item.appendChild(main);
        item.appendChild(scoreEl(pw.score, pw.score >= 70 ? "稳定" : "一般"));
        item.addEventListener("click", () =>
          navigator.clipboard.writeText(pw.code).then(() => toast("已复制"), () => { /* 忽略 */ }));
        list.appendChild(item);
      });
      body.appendChild(list);
    }

    if (p.xpath) { $("#xpathInput").value = p.xpath; pushHistory(p.xpath); }
  }
  $("#btnGrab").addEventListener("click", startGrab);
  $("#btnGrabInline").addEventListener("click", startGrab);
  /* ---------------------- 浏览器扩展一键安装 ---------------------- */
  const extInstall = { browsers: [], recommendKey: "", extDir: "", selKey: "", busy: false, lastResult: null };

  function setInstallState(kind, text) {
    const box = $("#installState");
    if (!box) return;
    box.className = "install-state" + (kind ? " " + kind : "");
    box.innerHTML = "";
    box.appendChild(el("span", "dot"));
    box.appendChild(document.createTextNode(text));
  }

  function strategyLabel(s) {
    return {
      auto: "现有浏览器（推荐）",
      flag: "启动参数加载（--load-extension）",
      cdp: "调试端口（CDP）",
      guided: "引导安装",
      policy: "企业策略强制安装",
    }[s] || s;
  }

  // 每种方式「装到哪」——用户最容易误解的地方，直接写在界面上
  const STRATEGY_HINT = {
    auto: "在所选的现有浏览器打开扩展页并复制目录，按提示完成手动加载；多个人资料时请确认目标窗口。",
    flag: "启动参数加载：会开独立 profile 的新浏览器窗口，不会安装到日常浏览器。",
    cdp: "调试端口（CDP）：在独立 profile 中临时加载，浏览器重启后需重新加载。",
    guided: "在现有浏览器打开扩展管理页，手动开启开发者模式并加载解压目录；若组织禁止安装，请联系管理员。",
    policy: "企业策略用于现有浏览器，但自托管安装有管理环境前提；写入成功不代表安装成功。普通个人电脑优先选择引导安装。", 
  };

  function updateStrategyHint() {
    const sel = document.querySelector('input[name="installStrategy"]:checked');
    const s = sel ? sel.value : "auto";
    const hint = $("#strategyHint");
    if (hint) hint.textContent = STRATEGY_HINT[s] || "";
    const pf = $("#policyField");
    if (pf) pf.hidden = s !== "policy";
    if (!extInstall.busy) $("#btnInstallRun").textContent = !$("#installAdv").checked || s === "auto" || s === "guided"
      ? "安装到现有浏览器" : s === "policy" ? "配置企业策略" : "启动独立实例";
    if (s === "policy") loadPolicyStatus();
  }

  function copyText(text, okMsg) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => toast(okMsg || "已复制"), () => toast("复制失败"));
  }

  function renderBrowsers() {
    const wrap = $("#installBrowsers");
    wrap.innerHTML = "";
    if (!extInstall.browsers.length) {
      wrap.appendChild(el("div", "grab-empty",
        "没有检测到 Chrome / Edge / Brave / Chromium。可点「引导安装」手动加载扩展目录。"));
      return;
    }
    extInstall.browsers.forEach((b) => {
      const item = el("label", "browser-item" + (b.key === extInstall.selKey ? " sel" : ""));
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "installBrowser";
      radio.value = b.key;
      radio.checked = b.key === extInstall.selKey;
      radio.addEventListener("change", () => { extInstall.selKey = b.key; renderBrowsers(); updateStrategyHint(); });
      item.appendChild(radio);

      const main = el("div", "browser-main");
      const nameRow = el("div", "browser-name");
      nameRow.appendChild(document.createTextNode(b.name));
      nameRow.appendChild(el("span", "browser-ver", b.version || ""));
      main.appendChild(nameRow);

      const tags = el("div", "browser-tags");
      tags.appendChild(el("span", "browser-tag" + (b.key === extInstall.recommendKey ? " rec" : ""),
        "推荐：" + strategyLabel(b.recommend)));
      tags.appendChild(el("span", "browser-tag", "手动加载后可持续使用"));
      main.appendChild(tags);

      if (b.note) main.appendChild(el("div", "browser-note", "⚠ " + b.note));
      item.appendChild(main);
      wrap.appendChild(item);
    });
  }

  function renderInstallResult(res) {
    extInstall.lastResult = res;
    const box = $("#installResult");
    box.innerHTML = "";
    if (!res) return;

    const cls = res.ok ? (res.warning || res.needsRestart || res.guided || !res.connected ? "warn" : "ok") : "err";
    const b = el("div", "res-box " + cls);
    const title = !res.ok
      ? "安装失败"
      : res.needsRestart
        ? "策略配置已写入，扩展安装尚未验证"
        : res.guided
          ? "请在现有浏览器完成加载"
          : res.connected
            ? "检测到扩展连接，请核对目标浏览器"
            : "浏览器已启动，正在等待扩展连接";
    b.appendChild(el("div", "res-title", title));

    const rows = [];
    if (res.browser) rows.push("浏览器：" + res.browser + (res.version ? "　" + res.version : ""));
    if (res.target) rows.push("安装位置：" + (res.target === "isolated" ? "独立实例（不是日常浏览器）" : "现有浏览器（请确认个人资料）"));
    if (res.strategy) rows.push("安装方式：" + strategyLabel(res.strategy) + (res.method ? "（" + res.method + "）" : ""));
    if (res.extId) rows.push("扩展 ID：" + res.extId);
    if (res.policyPath) rows.push("策略位置：" + res.policyPath);
    if (res.updateUrl) rows.push("更新地址：" + res.updateUrl);
    if (res.crxPath) rows.push("CRX 文件：" + res.crxPath);
    if (res.extDir) rows.push("扩展目录：" + res.extDir);
    if (res.stage) rows.push("执行阶段：" + res.stage);
    if (res.managementUrl) rows.push("扩展管理页：" + res.managementUrl);
    if (res.diagnostics && res.diagnostics.errorType) rows.push("系统错误：" +
      res.diagnostics.errorType + " · " + (res.diagnostics.systemError || "") +
      (res.diagnostics.winerror != null ? "（Windows 错误码 " + res.diagnostics.winerror + "）" : ""));
    if (res.error) rows.push("错误：" + res.error);
    if (res.warning) rows.push(res.warning);
    if (res.connected === false) rows.push("连接状态：尚未连回桌面版（可稍等几秒再点「重新检测连接」）");
    rows.forEach((t) => b.appendChild(el("div", null, t)));

    if (res.steps && res.steps.length) {
      const ol = document.createElement("ol");
      res.steps.forEach((s) => ol.appendChild(el("li", null, s)));
      b.appendChild(ol);
    }
    if (res.warnings && res.warnings.length) {
      const w = el("div", "policy-warn");
      w.appendChild(el("b", null, "请注意"));
      const ul = document.createElement("ul");
      res.warnings.forEach((s) => ul.appendChild(el("li", null, s)));
      w.appendChild(ul);
      b.appendChild(w);
    }
    box.appendChild(b);
    const diagnostic = el("button", "btn ghost sm", "复制安装诊断");
    diagnostic.addEventListener("click", () => copyText(JSON.stringify({
      ok: res.ok, browser: res.browser, browserKey: res.browserKey, version: res.version,
      strategy: res.strategy, target: res.target, stage: res.stage, connected: res.connected,
      policyConfigured: res.policyConfigured, installationVerified: res.installationVerified,
      error: res.error, warning: res.warning, diagnostics: res.diagnostics,
      extDir: res.extDir, policyPath: res.policyPath, extId: res.extId
    }, null, 2), "安装诊断已复制，可发给我排查"));
    box.appendChild(diagnostic);

    if (res.fallback === "guided") {
      const fb = el("button", "btn ghost sm", "改用引导安装（手动加载）");
      fb.addEventListener("click", () => runInstall("guided"));
      box.appendChild(fb);
    }
    if (res.extDir || res.path) {
      const cp = el("button", "btn ghost sm", "复制扩展目录路径");
      cp.addEventListener("click", () => copyText(res.extDir || res.path, "已复制扩展目录"));
      box.appendChild(cp);
    }
  }

  /* ---- 企业策略：状态查询 / 渲染 / 卸载 ---- */
  let policyQuery = 0;
  async function loadPolicyStatus() {
    const query = ++policyQuery;
    const browserKey = extInstall.selKey;
    const box = $("#policyBox");
    if (!box) return;
    box.innerHTML = "";
    box.appendChild(el("div", "policy-meta", "正在查询策略状态…"));
    try {
      const res = await (await fetch("/api/extension/policy-status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ browser: extInstall.selKey }),
      })).json();
      if (query !== policyQuery || browserKey !== extInstall.selKey) return;
      renderPolicyBox(res);
    } catch (e) {
      if (query !== policyQuery || browserKey !== extInstall.selKey) return;
      box.innerHTML = "";
      box.appendChild(el("div", "policy-warn", "无法查询策略状态：" + e.message));
    }
  }

  function renderPolicyBox(res) {
    const box = $("#policyBox");
    if (!box) return;
    box.innerHTML = "";
    const btn = $("#btnRemovePolicy");
    const configured = res && (res.policyConfigured != null ? res.policyConfigured : res.installed);
    if (btn) btn.hidden = !configured;

    if (configured) {
      const ok = el("div", "policy-ok");
      ok.appendChild(el("b", null, "检测到策略配置（不代表扩展已安装）"));
      const meta = el("div", "policy-meta");
      meta.appendChild(el("div", null, "扩展 ID：" + (res.extId || "")));
      meta.appendChild(el("div", null, "策略位置：" + (res.policyPath || "")));
      (res.mine || []).forEach((m) => {
        const d = el("div", null, "");
        d.appendChild(el("code", null, m));
        meta.appendChild(d);
      });
      box.appendChild(ok);
      box.appendChild(meta);
      box.appendChild(el("div", "policy-meta", "请在浏览器扩展管理页检查实际安装状态；策略可能被浏览器拒绝。切换方式不会自动移除原有策略。"));
      return;
    }

    if (res && res.supported === false) {
      box.appendChild(el("div", "policy-warn",
        "当前环境不支持企业策略安装：" + (res.reason || "仅支持 Windows")));
      return;
    }

    const warn = el("div", "policy-warn");
    warn.appendChild(el("b", null, "副作用（确认后再装）"));
    const ul = document.createElement("ul");
    [
      "浏览器会显示「由贵单位管理」横幅。",
      "扩展由策略接管，无法在扩展管理页直接删除（要用这里的「卸载策略」）。",
      "桌面版没运行时浏览器拉不到更新；已装上的版本仍可正常使用。",
      "写入当前用户策略（HKCU），不碰 HKLM；权限或安全软件仍可能拒绝写入，不应绕过。",
      "自托管扩展强制安装受设备管理条件限制；普通电脑不能保证成功，建议先用引导安装。", 
    ].forEach((t) => ul.appendChild(el("li", null, t)));
    warn.appendChild(ul);
    box.appendChild(warn);
    box.appendChild(el("div", "policy-meta",
      "安装后请完全退出浏览器（含托盘）再重新打开。首次生效时浏览器会从本机服务拉取 update.xml 与 CRX。"));
  }

  async function removePolicy() {
    const btn = $("#btnRemovePolicy");
    if (btn) btn.disabled = true;
    setInstallState("", "正在移除策略…");
    try {
      const res = await (await fetch("/api/extension/policy-remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ browser: extInstall.selKey }),
      })).json();
      const box = $("#installResult");
      box.innerHTML = "";
      const b = el("div", "res-box " + (res.ok ? "ok" : "err"));
      b.appendChild(el("div", "res-title", res.ok ? "已移除策略" : "移除失败"));
      if (res.error) b.appendChild(el("div", null, res.error));
      if (res.note) b.appendChild(el("div", null, res.note));
      if (res.steps && res.steps.length) {
        const ol = document.createElement("ol");
        res.steps.forEach((s) => ol.appendChild(el("li", null, s)));
        b.appendChild(ol);
      }
      box.appendChild(b);
      setInstallState(res.ok ? "ok" : "err",
        res.ok ? "已移除本扩展的策略条目" : (res.error || "移除失败"));
      loadPolicyStatus();
    } catch (e) {
      setInstallState("err", "请求失败：" + e.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function openInstallModal() {
    $("#installModal").hidden = false;
    $("#installAdv").checked = false;
    $("#installAdvBody").hidden = true;
    document.querySelector('input[name="installStrategy"][value="auto"]').checked = true;
    $("#installResult").innerHTML = "";
    setInstallState("", "正在检测本机浏览器…");
    try {
      const res = await (await fetch("/api/extension/browsers")).json();
      if (!res.ok) {
        setInstallState("err", res.error || "检测失败");
        return;
      }
      extInstall.browsers = res.browsers || [];
      extInstall.recommendKey = res.recommendKey || "";
      extInstall.extDir = res.extDir || "";
      extInstall.selKey = extInstall.selKey || res.recommendKey || (extInstall.browsers[0] || {}).key || "";
      $("#installPath").value = extInstall.extDir || res.dirError || "(未找到扩展目录)";

      if (res.connected) {
        setInstallState("ok", "检测到扩展连接；若来自独立实例，仍需在日常浏览器中加载");
      } else if (!extInstall.browsers.length) {
        setInstallState("warn", "未检测到 Chromium 系浏览器");
      } else {
        const rec = extInstall.browsers.find((b) => b.key === extInstall.selKey) || {};
        setInstallState("", `检测到 ${extInstall.browsers.length} 个浏览器 · 将在现有 ${rec.name || "浏览器"} 中打开扩展页`);
      }
      renderBrowsers();
      updateStrategyHint();
    } catch (e) {
      setInstallState("err", "检测失败：" + e.message);
    }
  }

  async function runInstall(strategy) {
    if (extInstall.busy) return;
    const strat = strategy || "auto";
    if (strat === "policy" && !window.confirm("企业策略可能被设备管理或安全限制拒绝；写入成功也不代表扩展已安装。它可能让浏览器显示「由贵单位管理」，扩展不能直接删除。确认继续写入当前用户策略吗？")) return;
    extInstall.busy = true;
    const btn = $("#btnInstallRun");
    const old = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>安装中…';
    setInstallState("", strat === "policy"
      ? "正在生成密钥、签名 CRX 并写入策略…"
      : strat === "auto" || strat === "guided" ? "正在复制扩展目录并打开现有浏览器的扩展页…"
      : "正在启动浏览器并加载扩展，首次可能要十几秒…");
    $("#installResult").innerHTML = "";
    try {
      const res = await api("/api/extension/install", {
        strategy: strat,
        browser: extInstall.selKey || "",
      });
      renderInstallResult(res);
      if (res.ok && res.needsRestart) {
        setInstallState("warn", "策略配置已写入，安装尚未验证；请到浏览器中检查实际状态");
      } else if (res.ok && res.guided) {
        setInstallState("warn", "已打开扩展管理页，仍需手动加载；此时尚未安装完成");
      } else if (res.ok && res.connected) {
        setInstallState("ok", "扩展已连接；请确认目标浏览器中的扩展状态");
      } else if (res.ok) {
        setInstallState("warn", "浏览器已启动，但扩展还没连回来");
      } else {
        setInstallState("err", res.error || "安装失败");
      }
      if (strat === "policy") loadPolicyStatus();
    } catch (e) {
      setInstallState("err", "请求失败：" + e.message);
      renderInstallResult({ ok: false, error: e.message, fallback: "guided" });
    } finally {
      extInstall.busy = false;
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  async function recheckBridge() {
    setInstallState("", "正在重新检测连接…");
    try {
      const res = await (await fetch("/api/health")).json();
      const n = (res.bridge && res.bridge.extensions) || 0;
      setBridgeState(true, n > 0);
      if (n > 0) setInstallState("ok", "检测到扩展连接（" + n + " 个）；请确认目标浏览器中已启用本扩展");
      else setInstallState("warn", "还没有扩展连上来。确认扩展已启用，并打开任意网页试试。");
    } catch (e) {
      setInstallState("err", "无法连接本机服务：" + e.message);
    }
  }

  $("#bridgeChip").addEventListener("click", openInstallModal);
  $("#btnInstallExtInline").addEventListener("click", openInstallModal);
  $("#btnCloseInstall").addEventListener("click", () => ($("#installModal").hidden = true));
  $("#installModal").addEventListener("click", (e) => {
    if (e.target === $("#installModal")) $("#installModal").hidden = true;
  });
  $("#btnInstallRun").addEventListener("click", () => {
    const sel = document.querySelector('input[name="installStrategy"]:checked');
    runInstall($("#installAdv").checked && sel ? sel.value : "auto");
  });
  $("#btnInstallGuided").addEventListener("click", () => runInstall("guided"));
  $("#btnRecheckBridge").addEventListener("click", recheckBridge);
  $("#btnRemovePolicy").addEventListener("click", removePolicy);
  // 切换安装方式时同步提示文案与策略面板
  document.querySelectorAll('input[name="installStrategy"]').forEach((r) => {
    r.addEventListener("change", updateStrategyHint);
  });
  updateStrategyHint();
  $("#installAdv").addEventListener("change", (e) => {
    $("#installAdvBody").hidden = !e.target.checked;
    if (!e.target.checked) document.querySelector('input[name="installStrategy"][value="auto"]').checked = true;
    updateStrategyHint();
  });
  $("#btnOpenExtDir").addEventListener("click", async () => {
    try {
      const res = await api("/api/extension/open-folder", {});
      if (!res.ok) toast(res.error || "打开失败");
    } catch (e) { toast("打开失败：" + e.message); }
  });
  $("#btnCopyExtDir").addEventListener("click", () =>
    copyText($("#installPath").value, "已复制扩展目录"));

  async function syncServerConfig() {
    try {
      const r = await fetch("/api/config");
      const j = await r.json();
      if (!j || !j.ok || !j.config) return;
      if (!localStorage.getItem("xpath-studio-config") && j.config.baseUrl) {
        localStorage.setItem("xpath-studio-config", JSON.stringify({
          baseUrl: j.config.baseUrl,
          apiKey: "",
          model: j.config.model || "",
        }));
      }
    } catch { /* 忽略 */ }
  }


  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      $("#settingsModal").hidden = true;
      $("#installModal").hidden = true;
    }
  });
  window.addEventListener("load", () => {
    renderHistory();
    $("#bridgeUrl").textContent = location.origin;
    syncServerConfig();
    connectBridge();
    fetch("/api/bridge/last").then(r => r.json()).then(r => {
      if (!lastPick && r.payload) renderPick(r.payload);
    }).catch(() => {});
  });
})();
