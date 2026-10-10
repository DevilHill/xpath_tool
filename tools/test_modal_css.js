/* 真实加载 index.html + style.css + app.js（jsdom），渲染「安装扩展」弹窗，
 * 然后断言**计算后**的布局属性。
 *
 * 这个测试是为了防一类具体的回归：全局 `input { width: 100% }` 曾经也套到了
 * radio / checkbox 上，导致单选按钮在 flex 行里撑满整行，把浏览器名挤成一列，
 * 整个弹窗布局崩掉。jsdom 不做排版，但 getComputedStyle 能正确解析级联，
 * 所以断言 width / flex 这些声明值是可靠的。
 *
 * 用法：node tools/test_modal_css.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const CSS = fs.readFileSync(path.join(ROOT, "app", "web", "style.css"), "utf8");
const APP_SRC = fs.readFileSync(path.join(ROOT, "app", "web", "app.js"), "utf8");

// 把外链样式表内联进 DOM，jsdom 才会参与级联计算
const HTML = fs.readFileSync(path.join(ROOT, "app", "web", "index.html"), "utf8")
  .replace(/<script src="app\.js"><\/script>/, "")
  .replace(/<link rel="stylesheet"[^>]*>/, `<style>${CSS}</style>`);

const dom = new JSDOM(HTML, { url: "http://127.0.0.1:8790/" });

global.window = dom.window;
global.document = dom.window.document;
global.location = dom.window.location;
Object.defineProperty(global, "navigator", {
  value: dom.window.navigator, configurable: true, writable: true
});
global.localStorage = dom.window.localStorage;
global.Event = dom.window.Event;
global.HTMLElement = dom.window.HTMLElement;
global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;
dom.window.Element.prototype.scrollIntoView = function () { /* no-op */ };
try {
  Object.defineProperty(dom.window.navigator, "clipboard", {
    value: { writeText: () => Promise.resolve() }, configurable: true
  });
} catch (e) { /* 忽略 */ }

const BROWSERS = [
  { key: "chrome", name: "Google Chrome", path: "C:/x/chrome.exe", version: "153.0.8010.53", major: 153,
    branded: true, cdp: true, flag: false, recommend: "cdp",
    note: "Chrome 137+ 已禁用 --load-extension，将改用 CDP 或引导安装" },
  { key: "edge", name: "Microsoft Edge", path: "C:/x/msedge.exe", version: "154.0.4258.37", major: 154,
    branded: false, cdp: true, flag: true, recommend: "flag", note: "" },
];

function fakeFetch(url, opts) {
  const p = String(url);
  let payload = { ok: true };
  if (p.includes("/api/config")) payload = { ok: true, config: { configured: false } };
  else if (p.includes("/api/parse")) payload = { ok: true, token: "t", count: 1, desc: { top: [] }, tree: { idx: 0, tag: "html", attrs: {}, text: "", children: [] } };
  else if (p.includes("/api/extension/browsers")) {
    payload = { ok: true, browsers: BROWSERS, recommendKey: "edge", extDir: "D:\\App\\XPathStudio\\extension",
      dirError: "", port: 8790, platform: "Windows", connected: 0, stats: {} };
  } else if (p.includes("/api/health")) {
    payload = { ok: true, version: "1.0", bridge: { clients: 1, extensions: 0, uis: 1, lastPickAt: 0 } };
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
}
global.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

class FakeWS {
  constructor(url) { this.url = url; this.readyState = 0; }
  send() { } close() { this.readyState = 3; if (this.onclose) this.onclose(); }
}
global.WebSocket = FakeWS;
dom.window.WebSocket = FakeWS;

let pass = 0;
const fails = [];
function check(name, cond, detail) {
  if (cond) { pass++; console.log(`  [OK]   ${name}`); }
  else { fails.push(name); console.log(`  [FAIL] ${name}` + (detail ? `  -> ${detail}` : "")); }
}
const $ = (s) => dom.window.document.querySelector(s);
const $$ = (s) => Array.from(dom.window.document.querySelectorAll(s));
const cs = (el) => dom.window.getComputedStyle(el);
const tick = (n = 5) => new Promise((r) => {
  let i = 0;
  const step = () => (++i >= n ? r() : setTimeout(step, 0));
  setTimeout(step, 0);
});

(async () => {
  console.log("=".repeat(62));
  console.log(" XPath Studio · 安装弹窗布局回归测试（jsdom + 计算样式）");
  console.log("=".repeat(62));

  new Function(APP_SRC)();
  await tick(6);

  $("#bridgeChip").click();
  await tick(8);
  // 弹窗每次打开默认收起高级选项；随后模拟用户展开。
  $("#installAdv").checked = true;
  $("#installAdv").dispatchEvent(new dom.window.Event("change"));

  console.log("\n[1] 全局输入样式不能污染单选 / 复选");
  const radio = $('.browser-item input[type="radio"]');
  const checkbox = $("#installAdv");
  const stratRadio = $('input[name="installStrategy"]');

  check("渲染出单选按钮", !!radio);
  check("单选按钮 width 不是 100%", cs(radio).width !== "100%", cs(radio).width);
  check("单选按钮 width 为 auto", cs(radio).width === "auto", cs(radio).width);
  check("单选按钮 flex-grow 为 0（不抢宽度）", cs(radio).flexGrow === "0", cs(radio).flexGrow);
  check("单选按钮 padding 为 0（不撑高）", cs(radio).padding === "0px", cs(radio).padding);
  check("复选框 width 不是 100%", cs(checkbox).width !== "100%", cs(checkbox).width);
  check("复选框 flex-grow 为 0", cs(checkbox).flexGrow === "0", cs(checkbox).flexGrow);
  check("安装方式单选 width 为 auto", cs(stratRadio).width === "auto", cs(stratRadio).width);
  check("单选/复选有 accent-color", !!cs(radio).accentColor || !!cs(radio)["accent-color"]);

  console.log("\n[2] 文本框仍然要占满整行");
  const textInput = $("#installPath");
  check("文本框 width 为 100%", cs(textInput).width === "100%", cs(textInput).width);
  check("文本框有内边距", cs(textInput).paddingTop === "9px", cs(textInput).paddingTop);
  check(".path-row 里的输入框可伸缩", cs(textInput).flexGrow === "1", cs(textInput).flexGrow);

  console.log("\n[3] 浏览器列表项的行内布局");
  const items = $$(".browser-item");
  check("渲染出 2 个条目", items.length === 2, String(items.length));
  check(".browser-item 是 flex 行", cs(items[0]).display === "flex", cs(items[0]).display);
  const main = items[0].querySelector(".browser-main");
  check(".browser-main 撑满剩余宽度", cs(main).flexGrow === "1", cs(main).flexGrow);
  check(".browser-main 允许收缩（min-width:0）", cs(main).minWidth === "0px" || cs(main).minWidth === "0", cs(main).minWidth);
  check("条目内部有间距", cs(items[0]).columnGap === "11px" || cs(items[0]).gap === "11px", cs(items[0]).gap);

  // 关键：单选按钮的宽度必须远小于列表项本身（否则就是它把文字挤走了）
  check("单选按钮不占据整行（声明宽度为 auto）",
    cs(radio).width === "auto" && cs(radio).flexGrow === "0",
    `width=${cs(radio).width} flexGrow=${cs(radio).flexGrow}`);

  console.log("\n[4] 标签 / 文案没有被压成一列（宽度可伸缩）");
  const nameRow = items[0].querySelector(".browser-name");
  check("浏览器名容器存在", !!nameRow);
  check(".browser-name 是 flex 行", cs(nameRow).display === "flex", cs(nameRow).display);
  const tags = items[0].querySelector(".browser-tags");
  check("标签容器允许换行", cs(tags).flexWrap === "wrap", cs(tags).flexWrap);

  console.log("\n[5] 高级选项区域");
  const advBody = $("#installAdvBody");
  check("高级选项已展开", advBody.hidden === false);
  const radioRow = $(".radio-row");
  check(".radio-row 是可换行的 flex", cs(radioRow).display === "flex" && cs(radioRow).flexWrap === "wrap",
    `${cs(radioRow).display}/${cs(radioRow).flexWrap}`);
  const radioLabel = $(".radio-row .radio");
  check(".radio 是 inline-flex 行", cs(radioLabel).display === "inline-flex", cs(radioLabel).display);

  console.log("\n[6] 状态条 / 提示块");
  check(".install-state 是 flex 行", cs($("#installState")).display === "flex", cs($("#installState")).display);
  // 桩 WebSocket 不会触发 onopen，所以抓取面板的安装提示还是 hidden 状态；
  // 这里显式展开，验证它的 CSS 规则本身没问题。
  const callout = $("#grabInstall");
  callout.hidden = false;
  check(".install-callout 是 flex 行", cs(callout).display === "flex", cs(callout).display);
  check(".install-callout 允许收缩", cs(callout.querySelector(".install-callout-text")).minWidth === "0px",
    cs(callout.querySelector(".install-callout-text")).minWidth);

  console.log("\n[7] 弹窗不会溢出视口");
  const modal = $("#installModal .modal");
  check("弹窗限高（max-height 生效）", cs(modal).maxHeight !== "none" && cs(modal).maxHeight !== "", cs(modal).maxHeight);
  check("弹窗是纵向 flex 容器", cs(modal).display === "flex" && cs(modal).flexDirection === "column",
    `${cs(modal).display}/${cs(modal).flexDirection}`);
  check("内容区可滚动", cs(modal.querySelector(".modal-body")).overflowY === "auto",
    cs(modal.querySelector(".modal-body")).overflowY);
  check("头尾不参与伸缩", cs(modal.querySelector(".modal-head")).flexShrink === "0",
    cs(modal.querySelector(".modal-head")).flexShrink);

  console.log("\n" + "=".repeat(62));
  if (fails.length) {
    console.log(` 结果：${pass} 通过 / ${fails.length} 失败 ❌`);
    fails.forEach((f) => console.log("   - " + f));
    process.exit(1);
  }
  console.log(` 结果：全部 ${pass} 项通过 ✅`);
})();
