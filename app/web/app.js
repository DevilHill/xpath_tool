/* ============================================================
   XPath Studio · 前端逻辑（原生 JS，无框架）
   ============================================================ */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    token: null,
    tree: null,
    parents: {},        // idx -> parentIdx
    nodeApi: {},        // idx -> { expand, collapse, row, node }
    rowMap: {},         // idx -> row element
    selected: null,
    hitIdxs: [],
    config: loadConfig(),
  };

  /* ---------------------- 通用工具 ---------------------- */
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

  /* ---------------------- 标签页 ---------------------- */
  $$("#sourceTabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$("#sourceTabs .tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      $$(".pane").forEach((p) => p.classList.toggle("active", p.dataset.pane === tab.dataset.tab));
    });
  });

  $$("#resultTabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$("#resultTabs .tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      $$(".r-pane").forEach((p) => p.classList.toggle("active", p.dataset.rpane === tab.dataset.rtab));
    });
  });

  function switchResultTab(name) {
    $$("#resultTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.rtab === name));
    $$(".r-pane").forEach((p) => p.classList.toggle("active", p.dataset.rpane === name));
  }

  /* ---------------------- 评分 / 徽章 ---------------------- */
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

  /* ---------------------- 文件上传 ---------------------- */
  const dropzone = $("#dropzone");
  const fileInput = $("#fileInput");
  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("over"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("over"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("over");
    if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", () => { if (fileInput.files[0]) readFile(fileInput.files[0]); });

  function readFile(file) {
    const reader = new FileReader();
    reader.onload = () => {
      $("#htmlInput").value = reader.result;
      // 切回粘贴页并解析
      $$("#sourceTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === "paste"));
      $$(".pane").forEach((p) => p.classList.toggle("active", p.dataset.pane === "paste"));
      toast(`已载入 ${file.name}`);
      parseDoc();
    };
    reader.readAsText(file, "utf-8");
  }

  /* ---------------------- 网址抓取 ---------------------- */
  $("#btnFetch").addEventListener("click", async () => {
    const url = $("#urlInput").value.trim();
    if (!url) return toast("请输入网址");
    const btn = $("#btnFetch");
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>抓取中…';
    try {
      const res = await api("/api/fetch", { url });
      if (!res.ok) throw new Error(res.error || "抓取失败");
      $("#htmlInput").value = res.html;
      $$("#sourceTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === "paste"));
      $$(".pane").forEach((p) => p.classList.toggle("active", p.dataset.pane === "paste"));
      toast(`抓取成功（${res.length} 字符）`);
      parseDoc();
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "抓取页面源码";
    }
  });

  /* ---------------------- 解析 ---------------------- */
  $("#btnParse").addEventListener("click", parseDoc);

  async function parseDoc() {
    const html = $("#htmlInput").value;
    if (!html.trim()) return toast("请先输入 HTML 内容");
    const btn = $("#btnParse");
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>解析中…';
    try {
      const res = await api("/api/parse", { html });
      if (!res.ok) throw new Error(res.error || "解析失败");
      state.token = res.token;
      state.tree = res.tree;
      state.parents = {};
      state.nodeApi = {};
      state.rowMap = {};
      state.selected = null;
      state.hitIdxs = [];
      buildParents(res.tree, null);
      renderTree(res.tree);
      $("#docStat").textContent = `${res.count} 节点`;
      $("#treeStat").textContent = `共 ${res.count} 个节点 · ${res.desc.top.slice(0, 4).map(([t, n]) => `${t}×${n}`).join(" ")}`;
      $("#genBlock").hidden = true;
      clearMatches();
      toast(`解析完成，共 ${res.count} 个节点`);
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 12h14M12 5l7 7-7 7"/></svg>解析文档';
    }
  }

  function buildParents(node, parentIdx) {
    state.parents[node.idx] = parentIdx;
    (node.children || []).forEach((c) => buildParents(c, node.idx));
  }

  /* ---------------------- DOM 树渲染（懒加载） ---------------------- */
  function renderTree(tree) {
    const box = $("#domTree");
    box.innerHTML = "";
    box.appendChild(renderNode(tree, 0));
  }

  function renderNode(node, depth) {
    const wrap = el("div", "tree-node");
    const row = el("div", "tree-row");
    row.dataset.idx = node.idx;

    const hasKids = node.children && node.children.length > 0;

    const tw = el("span", "tw" + (hasKids ? "" : " leaf"), hasKids ? "▸" : "");
    row.appendChild(tw);

    row.appendChild(el("span", "t-tag", "<" + node.tag));

    for (const [k, v] of Object.entries(node.attrs || {})) {
      row.appendChild(el("span", "t-attr-name", " " + k));
      row.appendChild(el("span", "t-attr-val", '="' + v + '"'));
    }
    row.appendChild(el("span", "t-tag", ">"));

    if (node.text) row.appendChild(el("span", "t-text", " " + node.text));

    const searchBlob = (node.tag + " " + Object.keys(node.attrs || {}).join(" ") + " " +
      Object.values(node.attrs || {}).join(" ") + " " + (node.text || "")).toLowerCase();
    row.dataset.search = searchBlob;

    wrap.appendChild(row);

    const kidsBox = el("div", "tree-children");
    kidsBox.style.display = "none";
    wrap.appendChild(kidsBox);

    let loaded = false;
    let expanded = false;

    const self = {
      node,
      row,
      expand() {
        if (!hasKids) return;
        if (!loaded) {
          node.children.forEach((c) => kidsBox.appendChild(renderNode(c, depth + 1)));
          loaded = true;
        }
        expanded = true;
        kidsBox.style.display = "";
        tw.textContent = "▾";
      },
      collapse() {
        if (!hasKids) return;
        expanded = false;
        kidsBox.style.display = "none";
        tw.textContent = "▸";
      },
      isExpanded: () => expanded,
      get kidsBox() { return kidsBox; },
      reload() { loaded = false; kidsBox.innerHTML = ""; this.expand(); },
    };

    state.nodeApi[node.idx] = self;
    state.rowMap[node.idx] = row;

    if (hasKids) {
      tw.addEventListener("click", (e) => {
        e.stopPropagation();
        expanded ? self.collapse() : self.expand();
      });
    }
    row.addEventListener("click", () => selectNode(node.idx));

    if (hasKids && depth < 2) self.expand();
    return wrap;
  }

  function expandTo(idx) {
    const chain = [];
    let cur = idx;
    while (cur != null && cur !== undefined) {
      chain.push(cur);
      cur = state.parents[cur];
    }
    chain.reverse();
    chain.forEach((i) => { const a = state.nodeApi[i]; if (a) a.expand(); });
  }

  /* ---------------------- 选中节点 ---------------------- */
  async function selectNode(idx) {
    // 取消旧选中
    if (state.selected != null && state.rowMap[state.selected]) {
      state.rowMap[state.selected].classList.remove("selected");
    }
    state.selected = idx;
    expandTo(idx);
    const row = state.rowMap[idx];
    if (row) {
      row.classList.add("selected");
      row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    if (state.token == null) return;
    try {
      const res = await api("/api/gen", { token: state.token, idx });
      if (!res.ok) return;
      renderGen(res);
      $("#xpathInput").value = res.best || "";
      if (res.best) validate(res.best);
    } catch (e) {
      /* 忽略 */
    }
  }

  function renderGen(res) {
    const block = $("#genBlock");
    block.hidden = false;
    const t = res.target || {};
    $("#genTarget").textContent = `<${t.tag}> #${t.idx}` + (t.dynamicId ? " · ⚠动态ID" : "");

    const list = $("#genList");
    list.innerHTML = "";
    (res.xpath || []).forEach((c) => {
      const item = el("div", "cand");
      item.appendChild(scoreBar(c.score));
      const main = el("div", "cand-main");
      main.appendChild(el("div", "cand-xpath", c.xpath));
      const meta = el("div", "cand-meta");
      meta.appendChild(el("span", "cand-label", c.label + (c.note ? " · " + c.note : "")));
      if (c.warn) meta.appendChild(el("span", "cand-note", "⚠ " + c.warn));
      main.appendChild(meta);
      item.appendChild(main);
      item.appendChild(countBadge(c.count));
      item.appendChild(scoreEl(c.score, c.level));
      item.addEventListener("click", () => {
        $("#xpathInput").value = c.xpath;
        validate(c.xpath, true);
      });
      list.appendChild(item);
    });

    // CSS 选择器
    const css = res.css;
    const cssBlock = $("#cssBlock");
    const cssList = $("#cssList");
    cssList.innerHTML = "";
    if (css && css.css) {
      cssBlock.hidden = false;
      const item = el("div", "cand");
      item.appendChild(scoreBar(css.score));
      const main = el("div", "cand-main");
      main.appendChild(el("div", "cand-xpath", css.css));
      const meta = el("div", "cand-meta");
      meta.appendChild(el("span", "cand-label", "CSS 选择器" + (css.count == null ? " · 未校验" : "")));
      main.appendChild(meta);
      item.appendChild(main);
      if (css.count != null) item.appendChild(countBadge(css.count));
      item.appendChild(scoreEl(css.score, css.level));
      item.addEventListener("click", () => {
        navigator.clipboard.writeText(css.css).then(() => toast("已复制 CSS"), () => toast("复制失败"));
      });
      cssList.appendChild(item);
    } else {
      cssBlock.hidden = true;
    }

    // Playwright
    const pw = res.playwright || [];
    const pwBlock = $("#pwBlock");
    const pwList = $("#pwList");
    pwList.innerHTML = "";
    if (pw.length) {
      pwBlock.hidden = false;
      pw.forEach((p) => {
        const item = el("div", "cand");
        item.appendChild(scoreBar(p.score));
        const main = el("div", "cand-main");
        main.appendChild(el("div", "cand-xpath", "page." + p.code));
        const meta = el("div", "cand-meta");
        meta.appendChild(el("span", "cand-label", "Playwright · " + p.label));
        main.appendChild(meta);
        item.appendChild(main);
        item.appendChild(scoreEl(p.score, p.score >= 70 ? "稳定" : "一般"));
        item.addEventListener("click", () => {
          navigator.clipboard.writeText(p.code).then(() => toast("已复制 Playwright 定位器"), () => toast("复制失败"));
        });
        pwList.appendChild(item);
      });
    } else {
      pwBlock.hidden = true;
    }
  }

  /* ---------------------- 校验 ---------------------- */
  $("#btnValidate").addEventListener("click", () => validate(null, true));
  $("#xpathInput").addEventListener("keydown", (e) => { if (e.key === "Enter") validate(null, true); });
  $("#btnCopy").addEventListener("click", async () => {
    const v = $("#xpathInput").value;
    if (!v) return;
    try { await navigator.clipboard.writeText(v); toast("已复制"); }
    catch { $("#xpathInput").select(); document.execCommand("copy"); toast("已复制"); }
  });
  $("#btnClear").addEventListener("click", () => {
    $("#xpathInput").value = "";
    $("#validateMsg").className = "msg";
    $("#validateMsg").textContent = "";
    clearMatches();
    $("#matchCount").textContent = "—";
    $("#genBlock").hidden = true;
  });

  async function validate(xpath, record) {
    if (state.token == null) return toast("请先解析文档");
    const xp = xpath != null ? xpath : $("#xpathInput").value;
    if (!xp.trim()) return;
    const msg = $("#validateMsg");
    msg.className = "msg loading";
    msg.innerHTML = '<span class="spin"></span>校验中…';
    try {
      const res = await api("/api/validate", { token: state.token, xpath: xp });
      if (res.ok === false) { msg.className = "msg err"; msg.textContent = res.error; return; }
      if (!res.valid) {
        msg.className = "msg err";
        msg.textContent = "✕ 表达式无效：" + res.error;
        clearMatches();
        $("#matchCount").textContent = "—";
        return;
      }
      const n = res.count;
      msg.className = "msg " + (n === 0 ? "warn" : n === 1 ? "ok" : "warn");
      msg.textContent = n === 0
        ? "⚠ 表达式有效，但没有匹配到任何节点"
        : n === 1
          ? "✓ 匹配唯一节点"
          : `⚠ 匹配到 ${n} 个节点（建议加条件缩小范围）` + (res.truncated ? "，仅显示前 500 条" : "");
      $("#matchCount").textContent = n + " 个";
      renderMatches(res.matches || []);
      highlightMatches(res.matches || []);
      if (record) pushHistory(xp);
    } catch (e) {
      msg.className = "msg err";
      msg.textContent = "请求失败：" + e.message;
    }
  }

  function renderMatches(matches) {
    const list = $("#matchList");
    list.innerHTML = "";
    if (!matches.length) {
      list.appendChild(el("p", "muted small", "没有匹配到节点。"));
      return;
    }
    matches.slice(0, 200).forEach((m, i) => {
      const item = el("div", "match-item");
      if (m.kind === "value") {
        item.appendChild(el("span", "match-idx", "值"));
        const body = el("div", "match-body");
        body.appendChild(el("div", "match-tag", "非节点结果"));
        body.appendChild(el("div", "match-preview", m.value));
        item.appendChild(body);
        list.appendChild(item);
        return;
      }
      item.appendChild(el("span", "match-idx", "#" + m.idx));
      const body = el("div", "match-body");
      body.appendChild(el("div", "match-tag", "<" + m.tag + ">"));
      const preview = Object.entries(m.attrs || {}).map(([k, v]) => `${k}="${v}"`).join(" ");
      body.appendChild(el("div", "match-preview", (preview + " " + (m.text || "")).trim() || "(无属性)"));
      item.appendChild(body);
      item.addEventListener("click", () => {
        if (m.idx != null) selectNode(m.idx);
      });
      list.appendChild(item);
    });
  }

  function clearMatches() {
    $$(".tree-row.hit").forEach((r) => r.classList.remove("hit"));
    state.hitIdxs = [];
    $("#matchList").innerHTML = "";
    $("#matchList").appendChild(el("p", "muted small", "执行校验后显示匹配到的节点。"));
  }

  function highlightMatches(matches) {
    $$(".tree-row.hit").forEach((r) => r.classList.remove("hit"));
    state.hitIdxs = [];
    const idxs = matches.filter((m) => m.idx != null).map((m) => m.idx);
    idxs.slice(0, 300).forEach((idx) => {
      expandTo(idx);
      const row = state.rowMap[idx];
      if (row) { row.classList.add("hit"); state.hitIdxs.push(idx); }
    });
  }

  /* ---------------------- 自然语言检索（离线） ---------------------- */
  $("#btnNL").addEventListener("click", nlSearch);
  $("#nlInput").addEventListener("keydown", (e) => { if (e.key === "Enter") nlSearch(); });

  async function nlSearch() {
    if (state.token == null) return toast("请先解析文档");
    const q = $("#nlInput").value.trim();
    if (!q) return toast("请输入描述");
    const list = $("#nlList");
    list.innerHTML = '<div class="cand"><div class="cand-main"><div class="cand-xpath"><span class="spin"></span>检索中…</div></div></div>';
    try {
      const res = await api("/api/nl", { token: state.token, query: q });
      list.innerHTML = "";
      if (!res.matches || !res.matches.length) {
        list.appendChild(el("p", "muted small", "没有找到相关节点，换个说法试试。"));
        return;
      }
      res.matches.forEach((m) => {
        const item = el("div", "cand");
        const main = el("div", "cand-main");
        main.appendChild(el("div", "cand-xpath", `<${m.tag}> ` + (m.text || Object.values(m.attrs || {})[0] || "")));
        const meta = el("div", "cand-meta");
        meta.appendChild(el("span", "cand-label", `#${m.idx}` + (m.reason ? " · " + m.reason : "")));
        main.appendChild(meta);
        item.appendChild(main);
        item.appendChild(el("span", "badge multi", "分 " + m.score));
        item.addEventListener("click", () => selectNode(m.idx));
        list.appendChild(item);
      });
    } catch (e) {
      list.innerHTML = "";
      toast(e.message);
    }
  }

  /* ---------------------- AI 生成 ---------------------- */
  $("#btnAI").addEventListener("click", aiGenerate);
  $("#aiInput").addEventListener("keydown", (e) => { if (e.key === "Enter") aiGenerate(); });

  async function aiGenerate() {
    if (state.token == null) return toast("请先解析文档");
    const instruction = $("#aiInput").value.trim();
    if (!instruction) return toast("请描述要定位的元素");
    const cfg = loadConfig();
    if (!cfg.apiKey) {
      toast("请先在「AI 设置」中填写 API Key");
      openSettings();
      return;
    }
    const msg = $("#aiMsg");
    const list = $("#aiList");
    msg.className = "msg loading";
    msg.innerHTML = '<span class="spin"></span>AI 正在分析页面结构…';
    list.innerHTML = "";
    const btn = $("#btnAI");
    btn.disabled = true;
    try {
      const res = await api("/api/ai", { token: state.token, instruction, config: cfg });
      if (!res.ok) {
        msg.className = "msg err";
        msg.textContent = "✕ " + res.error;
        return;
      }
      const v = res.validation;
      const n = v ? v.count : null;
      msg.className = "msg " + (n === 1 ? "ok" : "warn");
      msg.textContent = (res.explain ? res.explain + "  " : "") +
        (v ? `（本地校验：${v.valid ? n + " 个匹配" : "无效表达式"}）` : "");
      renderAiResults(res);
    } catch (e) {
      msg.className = "msg err";
      msg.textContent = "请求失败：" + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  function renderAiResults(res) {
    const list = $("#aiList");
    list.innerHTML = "";
    const all = [res.xpath, ...(res.alternatives || [])].filter(Boolean);
    all.forEach((xp, i) => {
      const item = el("div", "cand");
      const main = el("div", "cand-main");
      main.appendChild(el("div", "cand-xpath", xp));
      const meta = el("div", "cand-meta");
      meta.appendChild(el("span", "cand-label", i === 0 ? "AI 推荐" : "备选 " + i));
      main.appendChild(meta);
      item.appendChild(main);
      item.appendChild(el("span", "badge uni", "使用"));
      item.addEventListener("click", () => {
        $("#xpathInput").value = xp;
        validate(xp, true);
      });
      list.appendChild(item);
    });
    if (res.xpath) { $("#xpathInput").value = res.xpath; validate(res.xpath, true); }
  }

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

  /* ---------------------- DOM 过滤 / 展开折叠 ---------------------- */
  $("#domFilter").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    const rows = $$(".tree-row");
    if (!q) { rows.forEach((r) => r.classList.remove("dim")); return; }
    rows.forEach((r) => {
      const hit = (r.dataset.search || "").includes(q);
      r.classList.toggle("dim", !hit);
    });
  });

  $("#btnExpandAll").addEventListener("click", () => {
    Object.values(state.nodeApi).forEach((a) => a.expand());
  });
  $("#btnCollapseAll").addEventListener("click", () => {
    const root = state.tree;
    if (!root) return;
    // 仅保留根展开
    Object.entries(state.nodeApi).forEach(([idx, a]) => {
      if (Number(idx) !== root.idx) a.collapse();
    });
  });

  /* ---------------------- 批量验证 ---------------------- */
  $("#btnVerify").addEventListener("click", async () => {
    if (state.token == null) return toast("请先解析文档");
    const selectors = $("#verifyInput").value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!selectors.length) return toast("请输入至少一个定位器");
    const summary = $("#verifySummary");
    const list = $("#verifyList");
    summary.className = "msg loading";
    summary.innerHTML = '<span class="spin"></span>验证中…';
    list.innerHTML = "";
    try {
      const res = await api("/api/verify", { token: state.token, selectors });
      const ok = res.results.filter((r) => r.valid).length;
      const unique = res.results.filter((r) => r.valid && r.count === 1).length;
      summary.className = "msg " + (ok === res.results.length ? "ok" : "warn");
      summary.textContent = `共 ${res.results.length} 条：有效 ${ok} 条，其中唯一定位 ${unique} 条`;
      res.results.forEach((r) => {
        const item = el("div", "match-item");
        const st = r.valid ? (r.count === 1 ? "✓" : "⚠") : "✕";
        item.appendChild(el("span", "match-idx", st));
        const body = el("div", "match-body");
        body.appendChild(el("div", "match-tag", r.selector));
        body.appendChild(el("div", "match-preview",
          r.error ? r.error
            : r.note ? r.note
              : `${r.type.toUpperCase()} · 匹配 ${r.count} 个${r.count === 1 ? "（唯一）" : ""}`));

        // 失配时给出自愈建议（Healenium 式相似度）
        if ((r.heal || []).length) {
          const box = el("div", "heal-box");
          box.appendChild(el("div", "heal-title", "✚ 已失效，找到相似元素（点击采用）"));
          r.heal.forEach((h) => {
            const row = el("div", "heal-row");
            row.appendChild(el("span", "heal-score " + (h.confidence === "高" ? "hi" : h.confidence === "中" ? "mid" : "lo"),
              h.confidence + " " + Math.round((h.score || 0) * 100) + "%"));
            const hb = el("div", "heal-body");
            hb.appendChild(el("div", "heal-xpath", h.xpath));
            if (h.reason) hb.appendChild(el("div", "heal-reason", h.reason));
            row.appendChild(hb);
            row.addEventListener("click", async (e) => {
              e.stopPropagation();
              // 先让 selectNode 完成：它会用「该节点的最佳定位器」覆盖 XPath 输入框，
              // 顺序反了的话用户点出来的自愈建议会被它盖掉。
              if (h.idx != null) await selectNode(h.idx);
              $("#xpathInput").value = h.xpath;
              pushHistory(h.xpath);
              await validate(h.xpath, true);
              toast("已采用自愈建议（" + h.confidence + "置信度）");
            });
            box.appendChild(row);
          });
          body.appendChild(box);
        }

        item.appendChild(body);
        if (r.idx != null) item.addEventListener("click", () => selectNode(r.idx));
        list.appendChild(item);
      });
    } catch (e) {
      summary.className = "msg err";
      summary.textContent = "请求失败：" + e.message;
    }
  });

  /* ---------------------- 页面扫描 ---------------------- */
  let scanData = null;

  $("#btnScan").addEventListener("click", async () => {
    if (state.token == null) return toast("请先解析文档");
    const summary = $("#scanSummary");
    const list = $("#scanList");
    summary.className = "msg loading";
    summary.innerHTML = '<span class="spin"></span>扫描中…';
    list.innerHTML = "";
    try {
      const res = await api("/api/scan", { token: state.token });
      scanData = res.items || [];
      const stable = scanData.filter((x) => x.score >= 70).length;
      summary.className = "msg ok";
      summary.textContent = `找到 ${res.count} 个可交互元素，其中 ${stable} 个可用稳定定位器`;
      renderScanList(scanData);
    } catch (e) {
      summary.className = "msg err";
      summary.textContent = "请求失败：" + e.message;
    }
  });

  function renderScanList(items) {
    const list = $("#scanList");
    list.innerHTML = "";
    items.forEach((it) => {
      const item = el("div", "scan-item");
      item.appendChild(scoreBar(it.score));
      const body = el("div", "scan-body");
      body.appendChild(el("div", "scan-xpath", it.xpath));
      const meta = [it.tag, it.text].filter(Boolean).join(" · ");
      body.appendChild(el("div", "scan-meta", meta));
      item.appendChild(body);
      item.appendChild(scoreEl(it.score, it.level));
      item.addEventListener("click", () => {
        $("#xpathInput").value = it.xpath;
        pushHistory(it.xpath);
        if (it.idx != null) selectNode(it.idx);
      });
      item.addEventListener("dblclick", () => {
        navigator.clipboard.writeText(it.xpath).then(() => toast("已复制"), () => toast("复制失败"));
      });
      list.appendChild(item);
    });
  }

  $("#btnScanExport").addEventListener("click", () => {
    if (!scanData || !scanData.length) return toast("请先扫描");
    const lines = scanData.map((it) => `${it.xpath}\t# ${it.tag}${it.text ? " " + it.text : ""} [${it.score} ${it.level}]`);
    const text = lines.join("\n");
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "xpath-scan.txt";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("已导出 xpath-scan.txt");
  });

  /* ---------------------- 示例 ---------------------- */
  const SAMPLE = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>示例商城</title>
</head>
<body>
  <header class="site-header">
    <a class="logo" href="/">MyShop</a>
    <nav class="main-nav">
      <ul>
        <li><a href="/phones" data-category="phones">手机</a></li>
        <li><a href="/laptops" data-category="laptops">笔记本</a></li>
        <li><a href="/audio" data-category="audio">耳机</a></li>
      </ul>
    </nav>
    <div class="header-actions">
      <button id="search-btn" class="icon-btn" aria-label="搜索">搜索</button>
      <a href="/cart" class="cart-link">
        购物车 <span class="cart-badge" data-count="3">3</span>
      </a>
      <button id="login-btn" class="btn btn-primary" type="button">登录</button>
    </div>
  </header>

  <main class="content">
    <section class="hero">
      <h1>秋季新品上市</h1>
      <p>全场满 300 减 50</p>
      <a href="/promo" class="btn btn-lg">立即选购</a>
    </section>

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
      <article class="product-card" data-sku="A1003">
        <h3 class="product-title">便携蓝牙音箱</h3>
        <p class="price">¥ 299.00</p>
        <button class="add-to-cart" data-sku="A1003">加入购物车</button>
      </article>
    </section>

    <form id="login-form" class="login-box" action="/login" method="post">
      <h2>账号登录</h2>
      <label for="username">用户名</label>
      <input id="username" name="username" type="text" placeholder="请输入用户名" required>
      <label for="password">密码</label>
      <input id="password" name="password" type="password" placeholder="请输入密码" required>
      <button type="submit" class="btn btn-primary">登 录</button>
    </form>
  </main>

  <footer class="site-footer">
    <p>© 2026 MyShop. All rights reserved.</p>
  </footer>
</body>
</html>`;

  $("#btnSample").addEventListener("click", () => {
    $("#htmlInput").value = SAMPLE;
    $$("#sourceTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === "paste"));
    $$(".pane").forEach((p) => p.classList.toggle("active", p.dataset.pane === "paste"));
    parseDoc();
  });

  /* ---------------------- 浏览器扩展实时桥接 ---------------------- */
  const bridge = { ws: null, retry: 0, timer: null, connected: false, ext: false };
  let lastPick = null;

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
    switchResultTab("grab");
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
    $("#btnGrab").classList.remove("armed");
    switchResultTab("grab");
    const msg = $("#grabMsg");
    msg.className = "msg ok";
    msg.innerHTML = "✓ 已从浏览器抓取到元素" +
      (p.matchCount >= 0 ? `（该 XPath 在实时页面上匹配 ${p.matchCount} 个节点）` : "");

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
          navigator.clipboard.writeText(c.xpath).then(() => toast("已复制"), () => { /* 忽略 */ });
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

    // 操作
    const actions = el("div", "block-actions");
    if (p.pageHtml) {
      const b = el("button", "btn ghost sm", inFrame ? "载入该框架 HTML 到编辑器" : "载入该页面到编辑器");
      b.addEventListener("click", async () => {
        $("#htmlInput").value = p.pageHtml;
        $$("#sourceTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === "paste"));
        $$(".pane").forEach((pp) => pp.classList.toggle("active", pp.dataset.pane === "paste"));
        await parseDoc();
        if (p.xpath) { $("#xpathInput").value = p.xpath; await validate(p.xpath, true); }
        toast("已载入页面并校验");
      });
      actions.appendChild(b);
    }
    if (p.xpath) {
      const b2 = el("button", "btn ghost sm", "复制 XPath");
      b2.addEventListener("click", () =>
        navigator.clipboard.writeText(p.xpath).then(() => toast("已复制 XPath"), () => { /* 忽略 */ }));
      actions.appendChild(b2);
    }
    if (actions.childNodes.length) body.appendChild(actions);

    // 元素 HTML
    if (p.html) {
      body.appendChild(el("div", "sub-head", "元素 HTML"));
      body.appendChild(el("div", "grab-html", p.html));
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

  /* ---------------------- 快捷键 ---------------------- */
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); parseDoc(); }
    if (e.key === "Escape") {
      $("#settingsModal").hidden = true;
      $("#installModal").hidden = true;
    }
  });

  // 启动时载入示例；首次使用自动解析一次，方便直接看到效果
  window.addEventListener("load", () => {
    $("#htmlInput").value = SAMPLE;
    renderHistory();
    // 展示真实的桥接地址（浏览器扩展用它连接本机服务）
    const bridgeEl = $("#bridgeUrl");
    if (bridgeEl) bridgeEl.textContent = location.origin;
    syncServerConfig();
    connectBridge();
    if (!localStorage.getItem("xpath-studio-seen")) {
      localStorage.setItem("xpath-studio-seen", "1");
      parseDoc().then(() => {
        // 首次自动选中一个代表性节点，展示候选定位器
        const target = findFirst(state.tree, (n) => n.attrs && n.attrs.id === "login-btn");
        if (target) selectNode(target.idx);
      });
    }
  });

  // 本地没有配置时，从本机服务端配置补齐（浏览器扩展保存过的）
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

  function findFirst(node, pred) {
    if (pred(node)) return node;
    for (const c of node.children || []) {
      const r = findFirst(c, pred);
      if (r) return r;
    }
    return null;
  }
})();
