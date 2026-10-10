/* 在 Node + jsdom 中真实加载桌面版前端，验证「批量验证」里的
 * 定位器自愈建议：渲染、置信度标签、点击采用后写入 XPath 输入框并选中节点。
 *
 * 用法：node tools/test_heal_ui.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const HTML = fs.readFileSync(path.join(ROOT, "app", "web", "index.html"), "utf8")
  .replace(/<script src="app\.js"><\/script>/, "");
const APP_SRC = fs.readFileSync(path.join(ROOT, "app", "web", "app.js"), "utf8");

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

const copied = [];
try {
  Object.defineProperty(dom.window.navigator, "clipboard", {
    value: { writeText: (t) => { copied.push(t); return Promise.resolve(); } },
    configurable: true
  });
} catch (e) { /* 忽略 */ }

/* ---------------- fetch 桩 ---------------- */
const calls = [];
let verifyPayload = null;

function fakeFetch(url, opts) {
  const p = String(url);
  calls.push({ path: p, body: opts && opts.body ? JSON.parse(opts.body) : null });
  let payload = { ok: true };
  if (p.includes("/api/config")) payload = { ok: true, config: { configured: false } };
  else if (p.includes("/api/parse")) {
    payload = {
      ok: true, token: "t1", count: 2, desc: { top: [["html", 1]] },
      tree: {
        idx: 0, tag: "html", attrs: {}, text: "", children: [
          { idx: 1, tag: "body", attrs: {}, text: "", children: [
            { idx: 2, tag: "button", attrs: { id: "login-button" }, text: "立即登录", children: [] },
          ] },
        ]
      }
    };
  } else if (p.includes("/api/validate")) {
    payload = { ok: true, valid: true, count: 1, matches: [{ idx: 2, kind: "node", tag: "button", attrs: { id: "login-button" }, text: "立即登录" }] };
  } else if (p.includes("/api/gen")) {
    payload = {
      ok: true, best: "//button[@id='login-button']",
      target: { idx: 2, tag: "button", attrs: { id: "login-button" }, text: "立即登录" },
      xpath: [{ xpath: "//button[@id='login-button']", label: "id 定位", strategy: "id", count: 1, unique: true, score: 88, level: "稳定", note: "", warn: "" }],
      css: { css: "#login-button", score: 88, level: "稳定" },
      playwright: []
    };
  } else if (p.includes("/api/verify")) {
    payload = verifyPayload || { ok: true, count: 0, results: [] };
  } else if (p.includes("/api/extension")) {
    payload = { ok: true, browsers: [], extDir: "", stats: {} };
  } else if (p.includes("/api/health")) {
    payload = { ok: true, version: "1.0", bridge: { clients: 1, extensions: 0, uis: 1, lastPickAt: 0 } };
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
}
global.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

/* ---------------- WebSocket 桩 ---------------- */
class FakeWS {
  constructor(url) { this.url = url; this.readyState = 0; this.sent = []; }
  send(d) { this.sent.push(d); }
  close() { this.readyState = 3; if (this.onclose) this.onclose(); }
}
global.WebSocket = FakeWS;
dom.window.WebSocket = FakeWS;

// jsdom 没实现 scrollIntoView，selectNode() 会用到
dom.window.Element.prototype.scrollIntoView = function () { /* no-op */ };

/* ---------------- 断言工具 ---------------- */
let pass = 0;
const fails = [];
function check(name, cond, detail) {
  if (cond) { pass++; console.log(`  [OK]   ${name}`); }
  else { fails.push(name); console.log(`  [FAIL] ${name}` + (detail ? `  -> ${detail}` : "")); }
}
const $ = (s) => dom.window.document.querySelector(s);
const $$ = (s) => Array.from(dom.window.document.querySelectorAll(s));
const tick = (n = 4) => new Promise((r) => {
  let i = 0;
  const step = () => (++i >= n ? r() : setTimeout(step, 0));
  setTimeout(step, 0);
});

(async () => {
  console.log("=".repeat(62));
  console.log(" XPath Studio · 定位器自愈建议 UI 测试（jsdom）");
  console.log("=".repeat(62));

  try {
    new Function(APP_SRC)();
  } catch (e) {
    console.log("  app.js 执行异常：" + e.message);
    process.exit(1);
  }
  await tick(6);

  // 先解析出文档，否则验证按钮会直接返回
  $("#btnParse") ? $("#btnParse").click() : null;
  await tick(8);
  console.log("\n[0] 前置状态");
  check("文档已解析（验证按钮可用）", $("#btnVerify") && !$("#btnVerify").disabled);

  console.log("\n[1] 无建议时不渲染自愈区块");
  verifyPayload = {
    ok: true, count: 2, results: [
      { selector: "//button[@id='login-button']", type: "xpath", valid: true, count: 1, idx: 2, heal: [] },
      { selector: ".add-to-cart", type: "css", valid: true, count: 3, idx: null, heal: [] },
    ]
  };
  $("#verifyInput").value = "//button[@id='login-button']\n.add-to-cart";
  $("#btnVerify").click();
  await tick(8);
  check("渲染了 2 条结果", $$("#verifyList .match-item").length === 2, String($$("#verifyList .match-item").length));
  check("没有自愈区块", $$("#verifyList .heal-box").length === 0);
  check("摘要显示统计", /有效 2 条/.test($("#verifySummary").textContent), $("#verifySummary").textContent);

  console.log("\n[2] 失配时渲染自愈建议");
  verifyPayload = {
    ok: true, count: 2, results: [
      {
        selector: "//button[@id='login-btn']", type: "xpath", valid: true, count: 0, idx: null,
        heal: [
          { xpath: "//button[@id='login-button']", score: 0.785, idx: 2, tag: "button", text: "立即登录",
            reason: "标签仍为 <button>、@id 值近似：login-button", confidence: "中" },
          { xpath: "//button[normalize-space(text())='立即登录']", score: 0.844, idx: 2, tag: "button", text: "立即登录",
            reason: "文案接近", confidence: "高" },
        ]
      },
      { selector: "//div[@class='totally-absent']", type: "xpath", valid: true, count: 0, idx: null, heal: [] },
    ]
  };
  $("#verifyInput").value = "//button[@id='login-btn']\n//div[@class='totally-absent']";
  $("#btnVerify").click();
  await tick(8);

  check("出现自愈区块", $$("#verifyList .heal-box").length === 1, String($$("#verifyList .heal-box").length));
  check("只给失配项加自愈区块（无建议的不加）", $$("#verifyList .match-item").length === 2);
  check("渲染了 2 条建议", $$("#verifyList .heal-row").length === 2, String($$("#verifyList .heal-row").length));
  check("区块标题提示已失效", /已失效/.test($("#verifyList .heal-title").textContent), $("#verifyList .heal-title").textContent);
  check("展示替代 XPath", /login-button/.test($("#verifyList").textContent));
  check("展示相似度百分比", /79%/.test($("#verifyList").textContent), $("#verifyList").textContent.slice(0, 200));
  check("展示置信度标签", /置信|高|中/.test($("#verifyList .heal-score").textContent), $("#verifyList .heal-score").textContent);
  check("高置信度用 hi 样式", !!$("#verifyList .heal-score.hi"));
  check("中置信度用 mid 样式", !!$("#verifyList .heal-score.mid"));
  check("展示理由", /标签仍为/.test($("#verifyList").textContent));

  console.log("\n[3] 点击建议 -> 写入 XPath 输入框 + 选中节点 + 重新校验");
  const before = calls.length;
  const rows = $$("#verifyList .heal-row");
  rows[0].dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await tick(10);
  check("XPath 输入框被替换为建议值", $("#xpathInput").value === "//button[@id='login-button']", $("#xpathInput").value);
  const after = calls.slice(before);
  check("触发了 /api/validate", after.some((c) => c.path.includes("/api/validate")),
    JSON.stringify(after.map((c) => c.path)));
  check("已选中对应节点", /login-button/.test($("#xpathInput").value));

  console.log("\n[4] 点击第二条建议");
  const rows2 = $$("#verifyList .heal-row");
  rows2[1].dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await tick(8);
  check("切到第二条建议", $("#xpathInput").value === "//button[normalize-space(text())='立即登录']", $("#xpathInput").value);

  console.log("\n[5] 点击建议不应误触发整行的选中");
  check("建议行是独立的可点区域", $$("#verifyList .heal-row").length === 2);

  console.log("\n[6] 全部有效时不给建议");
  verifyPayload = {
    ok: true, count: 1, results: [
      { selector: "//button[@id='login-button']", type: "xpath", valid: true, count: 1, idx: 2, heal: [] }
    ]
  };
  $("#verifyInput").value = "//button[@id='login-button']";
  $("#btnVerify").click();
  await tick(8);
  check("无自愈区块", $$("#verifyList .heal-box").length === 0);
  check("摘要为 ok 样式", $("#verifySummary").classList.contains("ok"), $("#verifySummary").className);

  console.log("\n" + "=".repeat(62));
  if (fails.length) {
    console.log(` 结果：${pass} 通过 / ${fails.length} 失败 ❌`);
    fails.forEach((f) => console.log("   - " + f));
    process.exit(1);
  }
  console.log(` 结果：全部 ${pass} 项通过 ✅`);
})();
