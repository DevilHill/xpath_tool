/* 在 Node + jsdom 中真实加载桌面版前端（index.html + app.js），
 * 验证「浏览器抓取」桥接链路：WebSocket 连接、状态指示、抓取结果渲染、按钮触发。
 *
 * 用法：node tools/test_exe_ui.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const HTML = fs.readFileSync(path.join(ROOT, "app", "web", "index.html"), "utf8")
  // 手动 eval app.js，避免 jsdom 去加载外部脚本
  .replace(/<script src="app\.js"><\/script>/, "");
const APP_SRC = fs.readFileSync(path.join(ROOT, "app", "web", "app.js"), "utf8");

const dom = new JSDOM(HTML, { url: "http://127.0.0.1:8790/" });

/* ---- 全局桩 ---- */
global.window = dom.window;
global.document = dom.window.document;
global.location = dom.window.location;
// Node 22 的 global.navigator 只有 getter，需用 defineProperty 覆盖
Object.defineProperty(global, "navigator", {
  value: dom.window.navigator, configurable: true, writable: true
});
global.localStorage = dom.window.localStorage;
global.Event = dom.window.Event;
global.HTMLElement = dom.window.HTMLElement;
global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;

try {
  Object.defineProperty(dom.window.navigator, "clipboard", {
    value: { writeText: () => Promise.resolve() },
    configurable: true
  });
} catch (e) { /* 忽略 */ }

/* fetch 桩：记录调用并返回可预期结果 */
const calls = [];
let pickResponse = { ok: true, sent: 1, stats: { clients: 2, extensions: 1 } };

function fakeFetch(url, opts) {
  const p = String(url);
  calls.push({ path: p, body: opts && opts.body ? JSON.parse(opts.body) : null });
  let payload = { ok: true };
  if (p.includes("/api/config")) payload = { ok: true, config: { configured: false } };
  else if (p.includes("/api/parse")) payload = { ok: true, token: "t1", count: 1, desc: { top: [["html", 1]] }, tree: { idx: 0, tag: "html", attrs: {}, text: "", children: [] } };
  else if (p.includes("/api/bridge/pick")) payload = pickResponse;
  else if (p.includes("/api/validate")) payload = { ok: true, valid: true, count: 1, matches: [] };
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
}
global.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

/* WebSocket 桩 */
const sockets = [];
class FakeWS {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    sockets.push(this);
  }
  send(d) { this.sent.push(d); }
  close() { this.readyState = 3; if (this.onclose) this.onclose(); }
  _open() { this.readyState = 1; if (this.onopen) this.onopen(); }
  _msg(obj) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
}
global.WebSocket = FakeWS;
dom.window.WebSocket = FakeWS;

/* ---- 加载前端 ---- */
// eslint-disable-next-line no-eval
eval(APP_SRC);
dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
dom.window.dispatchEvent(new dom.window.Event("load"));

const $ = (s) => dom.window.document.querySelector(s);
const $$ = (s) => Array.from(dom.window.document.querySelectorAll(s));

let pass = 0;
const fails = [];
function check(name, cond, extra) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fails.push(name); console.log("  ✕ " + name + (extra ? "  -> " + extra : "")); }
}
const tick = () => new Promise((r) => setTimeout(r, 0));

const PICK = {
  tag: "button",
  id: "login-btn",
  classes: ["btn", "btn-primary"],
  attrs: { id: "login-btn", class: "btn btn-primary" },
  text: "登录",
  html: '<button id="login-btn" class="btn btn-primary">登录</button>',
  xpath: "//button[@id='login-btn']",
  candidates: [
    { xpath: "//button[@id='login-btn']", score: 88, level: "稳定", count: 1, label: "id 定位" },
    { xpath: "//button[text()='登录']", score: 62, level: "一般", count: 1, label: "文本定位", warn: "文本可能变化" }
  ],
  css: { css: "#login-btn", score: 88, level: "稳定", count: 1 },
  playwright: [{ code: "getByRole('button', {name:'登录'})", score: 80, label: "role+name" }],
  target: { score: 88, level: "稳定" },
  url: "https://shop.example.com/login",
  title: "示例站点",
  matchCount: 1,
  pageHtml: "<html><body><button id='login-btn'>登录</button></body></html>"
};

(async function main() {
  console.log("=".repeat(62));
  console.log(" 桌面版前端桥接测试（jsdom）");
  console.log("=".repeat(62));

  console.log("\n[1] WebSocket 连接");
  check("已创建 WebSocket", sockets.length >= 1, `count=${sockets.length}`);
  const ws = sockets[0];
  check("连到本机 /ws", !!ws && /^ws:\/\/127\.0\.0\.1:8790\/ws$/.test(ws.url), ws && ws.url);

  ws._open();
  await tick();
  const hello = ws.sent.map((s) => { try { return JSON.parse(s); } catch (e) { return null; } }).filter(Boolean)[0];
  check("握手后发送 hello", !!hello && hello.type === "hello", JSON.stringify(hello));
  check("以 ui 角色注册", !!hello && hello.role === "ui", hello && hello.role);

  console.log("\n[2] 连接状态指示");
  const chip = $("#bridgeChip");
  const chipText = $("#bridgeChipText");
  check("桥接状态芯片存在", !!chip && !!chipText);
  check("初始为未连接文案", /未连接|等待/.test(chipText.textContent), chipText.textContent);

  ws._msg({ type: "stats", stats: { clients: 2, extensions: 1 } });
  await tick();
  check("扩展连上后文案更新", chipText.textContent === "扩展已连接", chipText.textContent);
  check("芯片点亮 on 样式", chip.classList.contains("on"));
  check("抓取 tab 指示点点亮", $("#grabDot").classList.contains("on"));

  ws._msg({ type: "stats", stats: { clients: 1, extensions: 0 } });
  await tick();
  check("扩展断开后文案回退", /等待|未连接/.test(chipText.textContent), chipText.textContent);

  console.log("\n[3] 抓取结果渲染");
  ws._msg({ type: "picked", payload: PICK });
  await tick();

  check("自动切到「浏览器抓取」标签", $('[data-rpane="grab"]').classList.contains("active"));
  const tabOn = $("#resultTabs .tab.active");
  check("对应标签按钮高亮", !!tabOn && tabOn.dataset.rtab === "grab", tabOn && tabOn.dataset.rtab);

  const body = $("#grabBody");
  check("目标摘要卡片已渲染", !!body.querySelector(".grab-target"));
  check("显示标签名", /login-btn/.test(body.querySelector(".grab-title").textContent),
    body.querySelector(".grab-title").textContent);
  check("显示来源标题与地址", /示例站点/.test(body.querySelectorAll(".grab-sub")[0].textContent));
  check("显示实时匹配数", /匹配 1 个节点/.test($("#grabMsg").textContent), $("#grabMsg").textContent);
  check("提示为成功态", $("#grabMsg").classList.contains("ok"));

  const cands = body.querySelectorAll(".cand");
  check("候选定位器 + CSS + Playwright 均已渲染（>=4 条）", cands.length >= 4, `count=${cands.length}`);
  const subHeads = Array.from(body.querySelectorAll(".sub-head")).map((e) => e.textContent);
  check("含「候选定位器」小节", subHeads.includes("候选定位器"), subHeads.join("|"));
  check("含「CSS 选择器」小节", subHeads.includes("CSS 选择器"), subHeads.join("|"));
  check("含「Playwright 定位器」小节", subHeads.includes("Playwright 定位器"), subHeads.join("|"));
  check("含「元素 HTML」小节", subHeads.includes("元素 HTML"), subHeads.join("|"));

  check("最佳 XPath 已回填输入框", $("#xpathInput").value === "//button[@id='login-btn']", $("#xpathInput").value);
  check("已写入查询历史", /login-btn/.test($("#historyRow").textContent), $("#historyRow").textContent);
  check("元素 HTML 片段已展示", /login-btn/.test(body.querySelector(".grab-html").textContent));

  const btns = Array.from(body.querySelectorAll("button")).map((b) => b.textContent);
  check("提供「载入该页面到编辑器」", btns.includes("载入该页面到编辑器"), btns.join("|"));
  check("提供「复制 XPath」", btns.includes("复制 XPath"), btns.join("|"));
  check("动态值告警已展示", /文本可能变化/.test(body.textContent));

  ws._msg({ type: "picked", payload: Object.assign({}, PICK, {
    frame: { isTop: false, frameId: 7, url: "https://frame.example/", topUrl: PICK.url }
  }) });
  await tick();
  check("框架抓取明确提示作用域", /来自 iframe #7/.test(body.textContent));
  check("框架 Playwright 不冒充 page 定位", /frame.getByRole/.test(body.textContent) && !/page.getByRole/.test(body.textContent));
  check("载入按钮明确只加载框架HTML", /载入该框架 HTML/.test(body.textContent));

  console.log("\n[4] 抓取按钮");
  calls.length = 0;
  $("#btnGrab").click();
  await tick();
  await tick();
  const pickCall = calls.find((c) => c.path.includes("/api/bridge/pick"));
  check("点击按钮调用 /api/bridge/pick", !!pickCall, JSON.stringify(calls.map((c) => c.path)));
  check("按钮进入 armed 动画态", $("#btnGrab").classList.contains("armed"));
  check("提示切到浏览器操作", /切到浏览器/.test($("#grabMsg").textContent), $("#grabMsg").textContent);

  // 无扩展时的错误分支
  pickResponse = { ok: false, error: "没有已连接的浏览器扩展。", stats: { extensions: 0 } };
  calls.length = 0;
  $("#btnGrabInline").click();
  await tick();
  await tick();
  check("内联按钮同样触发抓取", !!calls.find((c) => c.path.includes("/api/bridge/pick")));
  check("无扩展时显示错误", $("#grabMsg").classList.contains("err"), $("#grabMsg").textContent);

  console.log("\n[5] 状态回报");
  pickResponse = { ok: true, sent: 1 };
  ws._msg({ type: "status", payload: { kind: "start-pick", ok: false, error: "当前标签页不支持脚本注入" } });
  await tick();
  check("扩展报错时同步到界面", /不支持脚本注入/.test($("#grabMsg").textContent), $("#grabMsg").textContent);

  $("#btnGrab").click();
  await tick();
  ws._msg({ type: "status", payload: { kind: "cancel" } });
  await tick();
  check("浏览器端取消时同步到界面", /取消/.test($("#grabMsg").textContent), $("#grabMsg").textContent);
  check("取消后移除 armed 动画态", !$("#btnGrab").classList.contains("armed"));

  console.log("\n" + "=".repeat(62));
  if (fails.length) {
    console.log(` 结果：${pass} 通过 / ${fails.length} 失败 ❌`);
    process.exit(1);
  }
  console.log(` 结果：全部 ${pass} 项通过 ✅`);
})();
