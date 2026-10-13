/* 桌面实时工作台：抓取、来源绑定、浏览器校验、清空与慢响应竞态。 */
"use strict";
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
const dom = new JSDOM(fs.readFileSync(path.join(root, "app/web/index.html"), "utf8"),
  { url: "http://127.0.0.1:8790/" });
Object.assign(global, { window: dom.window, document: dom.window.document,
  location: dom.window.location, localStorage: dom.window.localStorage });
Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });
Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.resolve() } });
const calls = [], sockets = [];
let response = { ok: true, valid: true, count: 1, highlighted: 1,
  matches: [{ kind: "node", tag: "button", attrs: { id: "login" }, text: "登录" }] };
let delayNext = false, release;
global.fetch = (url, opts) => {
  const body = opts && opts.body ? JSON.parse(opts.body) : null;
  calls.push({ url, body });
  let value = url.includes("/api/bridge/validate") ? (body.action === "clear" ? { ok: true, cleared: true } : response) :
    url.includes("/api/bridge/pick") ? { ok: true, sent: 1 } : { ok: true };
  const result = { ok: true, json: async () => value };
  if (url.includes("/api/bridge/validate") && delayNext) {
    delayNext = false;
    return new Promise(resolve => { release = () => resolve(result); });
  }
  return Promise.resolve(result);
};
global.WebSocket = class {
  constructor(url) { this.url = url; this.sent = []; sockets.push(this); }
  send(text) { this.sent.push(JSON.parse(text)); }
  open() { this.readyState = 1; this.onopen(); }
  message(msg) { this.onmessage({ data: JSON.stringify(msg) }); }
};
eval(fs.readFileSync(path.join(root, "app/web/app.js"), "utf8"));
window.dispatchEvent(new window.Event("load"));
const $ = s => document.querySelector(s);
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
let checks = 0;
function check(name, cond) { if (!cond) throw new Error(name); checks++; console.log("[OK] " + name); }
const pick = { tag: "button", id: "login", text: "登录", title: "测试网页", url: "https://example.test/",
  browserId: "chrome-instance", frame: { tabId: 8, frameId: 7, documentId: "doc-7", isTop: false, url: "https://frame.test/" },
  xpath: "//button[@id='login']", matchCount: 1,
  candidates: [{ xpath: "//button[@id='login']", score: 88, label: "id 定位", count: 1, level: "稳定" }],
  css: { css: "#login", score: 88, level: "稳定" }, playwright: [{ code: "getByRole('button')", score: 78 }] };

(async () => {
  await tick();
  const ws = sockets[0]; ws.open();
  check("ui 注册桥接", ws.sent[0].role === "ui");
  check("移除数据源与 DOM 面板", !$("#htmlInput") && !$("#domTree") && !$("#sourceTabs"));
  check("移除快照工具与示例", !$("#btnSample") && !$("#btnNL") && !$("#btnVerify") && !$("#btnScan"));
  check("不自动解析示例", !calls.some(c => c.url === "/api/parse"));
  $("#xpathInput").value = "//button"; $("#btnValidate").click(); await tick();
  check("抓取前不发送校验", !calls.some(c => c.url === "/api/bridge/validate"));
  ws.message({ type: "stats", stats: { extensions: 1 } });
  check("扩展状态与安装提示同步", $("#bridgeChip").classList.contains("on") && $("#grabInstall").hidden);
  ws.message({ type: "picked", payload: pick });
  check("抓取回填 XPath", $("#xpathInput").value === pick.xpath);
  check("目标摘要与框架作用域保留", /login/.test($("#grabBody").textContent) && /iframe #7/.test($("#grabBody").textContent));
  check("候选 CSS 与 Playwright 保留", /CSS 选择器/.test($("#grabBody").textContent) && /frame.getByRole/.test($("#grabBody").textContent));
  check("不提供载入页面或 HTML 面板", !/载入|元素 HTML/.test($("#grabBody").textContent));
  $("#btnValidate").click(); await tick(); await tick();
  const validation = calls.find(c => c.url === "/api/bridge/validate");
  check("校验指向捕获浏览器", validation.body.target.browserId === "chrome-instance");
  check("校验保留原标签和文档", validation.body.target.tabId === 8 && validation.body.target.documentId === "doc-7");
  check("浏览器确认后显示同步高亮", /同步高亮/.test($("#validateMsg").textContent) && $("#matchCount").textContent === "1");
  check("真实匹配摘要渲染", /登录/.test($("#matchList").textContent));
  response = { ok: true, valid: true, count: 0, highlighted: 0, matches: [] };
  $("#xpathInput").dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter" })); await tick();
  check("Enter 校验零匹配并清除", /已清除/.test($("#validateMsg").textContent));
  response = { ok: true, valid: false, count: 0, error: "Invalid XPath", matches: [] };
  $("#btnValidate").click(); await tick();
  check("非法表达式不误报高亮", /表达式无效/.test($("#validateMsg").textContent) && $("#validateMsg").classList.contains("err"));
  response = { ok: true, valid: true, count: 1, highlighted: 0, matches: [{ kind: "value", value: "5" }] };
  $("#btnValidate").click(); await tick();
  check("标量值不声称高亮元素", /无元素可高亮/.test($("#validateMsg").textContent) && $("#matchList").textContent === "5");
  response = { ok: false, error: "目标页面已刷新，请重新抓取" };
  $("#btnValidate").click(); await tick();
  check("页面失效提示重新抓取", /重新抓取/.test($("#validateMsg").textContent));
  response = { ok: true, valid: true, count: 4, highlighted: 4, matches: [] };
  delayNext = true; $("#xpathInput").value = "//button"; $("#btnValidate").click(); await tick();
  $("#xpathInput").value = "//input"; $("#xpathInput").dispatchEvent(new window.Event("input"));
  response = { ok: true, valid: true, count: 2, highlighted: 2, matches: [] };
  $("#btnValidate").click();
  release(); await tick(); await tick();
  check("慢结果不覆盖新表达式", $("#matchCount").textContent === "2" && $("#xpathInput").value === "//input");
  $("#btnClear").click(); await tick();
  check("清空同步请求清除浏览器高亮", calls.at(-1).body.action === "clear" && /高亮已清除/.test($("#validateMsg").textContent));
  $("#btnGrab").click(); await tick();
  check("抓取入口仍通知扩展", calls.at(-1).url === "/api/bridge/pick" && $("#btnGrab").classList.contains("armed"));
  ws.message({ type: "status", payload: { kind: "cancel" } });
  check("浏览器取消同步", /取消/.test($("#grabMsg").textContent) && !$("#btnGrab").classList.contains("armed"));
  console.log(`实时工作台：${checks} 项通过`); process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
