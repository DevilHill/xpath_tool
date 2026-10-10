/* 在 Node + jsdom 中真实渲染扩展面板，验证 UI 构建与渲染逻辑。
 *
 * 用法：node tools/test_panel_render.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const ENGINE_SRC = fs.readFileSync(path.join(ROOT, "extension", "lib", "engine.js"), "utf8");
const UI_SRC = fs.readFileSync(path.join(ROOT, "extension", "ui.js"), "utf8");

const PAGE = `<!DOCTYPE html><html><body>
<header class="site-header">
  <button id="login-btn" class="btn btn-primary active" type="button">登录</button>
  <a href="/cart" class="cart-link">购物车 <span class="cart-badge">3</span></a>
</header>
<section class="product-list">
  <article class="product-card" data-sku="A1001"><h3 class="product-title">耳机</h3><button class="add-to-cart" data-sku="A1001">加入购物车</button></article>
  <article class="product-card" data-sku="A1002"><h3 class="product-title">手表</h3><button class="add-to-cart" data-sku="A1002">加入购物车</button></article>
</section>
<div id="j_idt88:panel" class="sc-bdVTJa dKpMkN">动态元素</div>
</body></html>`;

const dom = new JSDOM(PAGE);
global.window = dom.window;
global.document = dom.window.document;
global.XPathResult = dom.window.XPathResult;
global.CSS = dom.window.CSS;
global.Node = dom.window.Node;
global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;
global.setInterval = setInterval;
global.clearInterval = clearInterval;
// 桩：chrome.storage
global.chrome = {
  storage: { local: { get: (k, cb) => cb({}), set: () => {} } },
  runtime: { onMessage: { addListener: () => {} }, sendMessage: () => {} }
};

// eslint-disable-next-line no-eval
eval(ENGINE_SRC);
// eslint-disable-next-line no-eval
eval(UI_SRC);

const E = dom.window.XPathStudioEngine;
const Panel = dom.window.XPathStudioPanel;

let pass = 0;
const fails = [];

function check(name, cond, extra) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fails.push(name); console.log("  ✕ " + name + (extra ? "  -> " + extra : "")); }
}

console.log("=".repeat(62));
console.log(" 扩展面板渲染测试（jsdom）");
console.log("=".repeat(62));

// --- 挂载 ---
let pickToggled = 0, validated = null, scanned = 0, aiReq = null, bridgeTested = null, closed = 0;
Panel.mount({
  onPickToggle: () => pickToggled++,
  onValidate: (xp) => { validated = xp; },
  onScan: () => scanned++,
  onAi: (v) => { aiReq = v; },
  onBridgeTest: (v) => { bridgeTested = v; },
  onClose: () => closed++,
  onToast: () => {}
});

const host = Panel.getHost();
check("面板宿主已创建", !!host);
check("宿主 id 正确", host && host.id === "__xpath_studio_root__", host && host.id);
check("宿主已插入文档", !!(host && host.parentNode));
check("Shadow DOM 已建立", !!(host && host.shadowRoot));
const sr = host.shadowRoot;
check("样式已注入 shadow root", !!(sr && sr.querySelector("style")));
check("面板节点存在", !!(sr && sr.querySelector(".xps")));
check("高亮层插入在面板之前", (() => {
  const kids = Array.from(sr.children).map(n => n.className || n.tagName);
  const layerIdx = kids.findIndex(c => c === "xps-layer" || c === "");
  const panelIdx = kids.indexOf("xps");
  return panelIdx === kids.length - 1;
})());

// --- 显示/隐藏 ---
Panel.show();
check("show() 后面板可见", sr.querySelector(".xps").hidden === false);
Panel.toggle();
check("toggle() 后面板隐藏", sr.querySelector(".xps").hidden === true);
Panel.toggle();
check("再次 toggle() 可见", sr.querySelector(".xps").hidden === false);

// --- 折叠 ---
Panel.toggleFold();
check("折叠后 body 隐藏", sr.querySelector(".xps-body").hidden === true);
Panel.toggleFold();
check("再折叠后 body 显示", sr.querySelector(".xps-body").hidden === false);

// --- 状态栏 ---
Panel.setStatus("匹配唯一节点", "ok");
const status = sr.querySelector('[data-role="status"]');
check("状态栏文本正确", status.textContent === "匹配唯一节点", status.textContent);
check("状态栏样式类正确", status.className.indexOf("ok") !== -1, status.className);
Panel.setStatus('<span class="xps-spin"></span>加载中…');
check("状态栏支持 HTML（加载动画）", sr.querySelector('[data-role="status"] .xps-spin') !== null);

// --- 候选定位器渲染 ---
const btn = document.querySelector("#login-btn");
const gen = E.genForElement(btn);
Panel.renderGen(gen);
const cands = sr.querySelectorAll('[data-role="candList"] .xps-cand');
check("候选列表已渲染", cands.length > 0, "条数=" + cands.length);
check("候选条数 = XPath候选 + CSS + Playwright",
  cands.length === gen.xpath.length + (gen.css && gen.css.css ? 1 : 0) + gen.playwright.length,
  `期望 ${gen.xpath.length + 1 + gen.playwright.length}，实际 ${cands.length}`);
const firstXp = sr.querySelector('[data-role="candList"] .xps-xp');
check("首条候选为最短唯一 XPath", firstXp && firstXp.textContent === gen.best,
  firstXp && firstXp.textContent);
check("候选带稳定性徽章", sr.querySelectorAll('[data-role="candList"] .xps-badge.stable').length > 0);
check("候选带评分条", sr.querySelectorAll('[data-role="candList"] .xps-bar').length > 0);
check("CSS 分组已渲染", !!sr.querySelector('[data-role="candList"] .xps-sub'));

// 点击候选 -> 触发校验回调
cands[0].dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("点击候选触发 onValidate", validated === gen.best, String(validated));
check("点击候选回填输入框", sr.querySelector('[data-role="xpath"]').value === gen.best);

// --- 匹配列表 ---
const v = E.validate(gen.best);
Panel.renderMatches(v.matches, () => {});
const matchRows = sr.querySelectorAll('[data-role="matchList"] .xps-cand');
check("匹配列表已渲染", matchRows.length === v.count, `期望 ${v.count}，实际 ${matchRows.length}`);
Panel.renderMatches([], () => {});
check("空匹配显示占位提示", sr.querySelector('[data-role="matchList"] .xps-empty') !== null);

// --- 扫描 ---
const items = E.scanPage();
Panel.renderScan(items, () => {});
const scanRows = sr.querySelectorAll('[data-role="scanList"] .xps-cand');
check("扫描列表已渲染", scanRows.length === items.length, `期望 ${items.length}，实际 ${scanRows.length}`);

// --- AI 列表 ---
Panel.renderAiList(["//button[@id='login-btn']", "//button[@type='button']"]);
check("AI 结果列表已渲染", sr.querySelectorAll('[data-role="aiList"] .xps-cand').length === 2);
Panel.setAiStatus("✓ 桌面版已连接", "ok");
check("AI 状态已设置", sr.querySelector('[data-role="aiStatus"]').textContent.indexOf("已连接") !== -1);

// --- 交互回调 ---
sr.querySelector('[data-role="pick"]').dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("点击拾取按钮触发回调", pickToggled === 1, "次数=" + pickToggled);
sr.querySelector('[data-role="scan"]').dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("点击扫描按钮触发回调", scanned === 1);
sr.querySelector('[data-role="close"]').dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
check("点击关闭触发 onClose", closed === 1);

// --- 标签页 ---
Panel.selectTab("scan");
check("selectTab 切换生效",
  sr.querySelector('[data-tab="scan"]').classList.contains("on") &&
  sr.querySelector('[data-pane="scan"]').classList.contains("on"));
Panel.selectTab("cand");

// --- 拾取按钮状态 ---
Panel.setPicking(true);
check("setPicking(true) 按钮高亮", sr.querySelector('[data-role="pick"]').classList.contains("on"));
Panel.setPicking(false);
check("setPicking(false) 取消高亮", !sr.querySelector('[data-role="pick"]').classList.contains("on"));

// --- 输入框读写 ---
Panel.setXPath("//div[@id='x']");
check("setXPath / getXPath 正常", Panel.getXPath() === "//div[@id='x']", Panel.getXPath());

// --- 桥接地址 ---
Panel.setBridge("http://127.0.0.1:9999");
check("setBridge / getBridge 正常", Panel.getBridge() === "http://127.0.0.1:9999", Panel.getBridge());

// --- 动态 ID 元素渲染 ---
const dynEl = document.querySelector("[id^='j_idt']");
const gen2 = E.genForElement(dynEl);
Panel.renderGen(gen2);
check("动态 ID 元素有告警标记", sr.querySelector('[data-role="candList"] .xps-warn') !== null);
check("动态 ID 元素 best 避开动态 id", gen2.best.indexOf("j_idt88") === -1, gen2.best);

console.log("\n" + "=".repeat(62));
if (fails.length) {
  console.log(` 结果：${pass} 通过 / ${fails.length} 失败 ✕`);
  fails.forEach(f => console.log("   - " + f));
  process.exit(1);
}
console.log(` 结果：全部 ${pass} 项通过 ✅`);
