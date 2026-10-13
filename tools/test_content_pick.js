/* 在 Node + jsdom 中加载内容脚本，验证「桌面版驱动」的拾取流程：
 *   start-pick -> 覆盖层出现 -> 悬停高亮 -> 普通点击无效 -> Ctrl+左键选中 -> 回传 picked
 *
 * 用法：node tools/test_content_pick.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");

const PAGE = `<!DOCTYPE html><html><body>
<header><button id="login-btn" class="btn btn-primary active" type="button">登录</button></header>
<section>
  <article class="product-card"><h3 class="product-title">耳机</h3>
    <button class="add-to-cart" data-sku="A1001">加入购物车</button></article>
</section>
</body></html>`;

const dom = new JSDOM(PAGE, { url: "https://shop.example.com/login" });

global.window = dom.window;
global.document = dom.window.document;
global.location = dom.window.location;
global.XPathResult = dom.window.XPathResult;
global.CSS = dom.window.CSS;
global.Node = dom.window.Node;
global.MouseEvent = dom.window.MouseEvent;
global.KeyboardEvent = dom.window.KeyboardEvent;
global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;
global.setInterval = setInterval;
global.clearInterval = clearInterval;

/* ---- chrome 桩 ---- */
const sent = [];
const listeners = [];
global.chrome = {
  runtime: {
    onMessage: { addListener: (fn) => listeners.push(fn) },
    sendMessage: (msg, cb) => { sent.push(msg); if (cb) cb({ ok: true, via: "ws" }); },
    lastError: null
  },
  storage: { local: { get: (k, cb) => cb({}), set: () => {} } }
};
dom.window.chrome = global.chrome;

/* jsdom 不实现 elementFromPoint，桩成返回指定元素 */
let pointTarget = null;
dom.window.document.elementFromPoint = function () { return pointTarget; };

/* ---- 加载三个脚本 ---- */
// eslint-disable-next-line no-eval
eval(read("extension/lib/engine.js"));
// eslint-disable-next-line no-eval
eval(read("extension/ui.js"));
// eslint-disable-next-line no-eval
eval(read("extension/content.js"));

const Engine = dom.window.XPathStudioEngine;
const Panel = dom.window.XPathStudioPanel;
const $ = (s) => dom.window.document.querySelector(s);

let pass = 0;
const fails = [];
function check(name, cond, extra) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fails.push(name); console.log("  ✕ " + name + (extra ? "  -> " + extra : "")); }
}
const tick = () => new Promise((r) => setTimeout(r, 0));

function fire(msg) {
  let resp = null;
  listeners.forEach((fn) => fn(msg, {}, (r) => { resp = r; }));
  return resp;
}

function mouse(type, el, opts) {
  const o = Object.assign({ bubbles: true, cancelable: true, clientX: 10, clientY: 10 }, opts || {});
  el.dispatchEvent(new dom.window.MouseEvent(type, o));
}

const OVERLAY_ID = "__xpath_studio_overlay__";
const overlay = () => dom.window.document.getElementById(OVERLAY_ID);

(async function main() {
  console.log("=".repeat(62));
  console.log(" 内容脚本拾取流程测试（jsdom）");
  console.log("=".repeat(62));

  console.log("\n[1] 桌面版下发 start-pick");
  check("加载后尚未创建覆盖层", !overlay());
  const r1 = fire({ type: "start-pick", sessionId: "initial-session" });
  await tick();
  check("返回 picking=true", !!r1 && r1.picking === true, JSON.stringify(r1));
  const ov = overlay();
  check("覆盖层已创建", !!ov, OVERLAY_ID);
  check("覆盖层是独立宿主（与面板宿主不同 id）", !!ov && ov.id !== Engine.UI_ROOT_ID);
  check("面板被静默挂载但不可见（桌面版驱动时不弹面板）", !Panel.isVisible());
  check("覆盖层带 data-xps 标记", !!ov && ov.getAttribute("data-xps") === "1");
  check("已显示操作提示条", !!ov && !!ov.shadowRoot.querySelector(".ov-bar"));
  check("提示条含 Ctrl 指引", !!ov && /Ctrl/.test(ov.shadowRoot.querySelector(".ov-bar").innerHTML));

  console.log("\n[2] 悬停高亮");
  pointTarget = $("#login-btn");
  mouse("mousemove", dom.window.document);
  await tick();
  const pickBox = ov.shadowRoot.querySelector(".ov-pick");
  check("悬停出现高亮框", !!pickBox);
  check("悬停显示元素描述浮层", !!ov.shadowRoot.querySelector(".ov-tip"));
  check("描述含 id", /login-btn/.test(ov.shadowRoot.querySelector(".ov-tip").textContent),
    ov.shadowRoot.querySelector(".ov-tip").textContent);

  console.log("\n[3] 手势：普通左键无效，Ctrl+左键选中");
  sent.length = 0;
  mouse("click", $("#login-btn"), { ctrlKey: false });
  await tick();
  check("普通左键不回传", sent.length === 0, JSON.stringify(sent.map((s) => s.type)));
  check("普通左键后仍在拾取（提示条还在）", !!ov.shadowRoot.querySelector(".ov-bar"));
  check("普通左键提示需要 Ctrl", /Ctrl/.test(ov.shadowRoot.querySelector(".ov-bar").innerHTML));

  mouse("click", $("#login-btn"), { ctrlKey: true });
  await tick();
  check("Ctrl+左键仅锁定，不提前回传", !sent.some((s) => s.type === "picked"));
  check("锁定后显示确认卡片", !!ov.shadowRoot.querySelector(".ov-review"));
  ov.shadowRoot.querySelector('[data-action="confirm"]').click();
  await tick();
  const picked = sent.find((s) => s.type === "picked");
  check("确认后触发 picked 回传", !!picked, JSON.stringify(sent.map((s) => s.type)));
  check("拾取结束（提示条已移除）", !ov.shadowRoot.querySelector(".ov-bar"));
  check("高亮框已清理", !ov.shadowRoot.querySelector(".ov-pick"));

  console.log("\n[4] 回传负载内容");
  const p = (picked && picked.payload) || {};
  check("tag 正确", p.tag === "button", p.tag);
  check("id 正确", p.id === "login-btn", p.id);
  check("classes 为数组", Array.isArray(p.classes) && p.classes.indexOf("btn") >= 0, JSON.stringify(p.classes));
  check("最佳 XPath 正确", p.xpath === "//button[@id='login-btn']", p.xpath);
  check("含候选定位器", Array.isArray(p.candidates) && p.candidates.length > 0, p.candidates && p.candidates.length);
  check("含 CSS 定位器", !!(p.css && p.css.css), JSON.stringify(p.css));
  check("含 Playwright 定位器", Array.isArray(p.playwright) && p.playwright.length > 0);
  check("含元素 HTML", /login-btn/.test(p.html || ""), (p.html || "").slice(0, 60));
  check("含页面 URL", p.url === "https://shop.example.com/login", p.url);
  check("含页面标题", typeof p.title === "string");
  check("含实时匹配数", p.matchCount === 1, String(p.matchCount));
  check("不再传输整页 HTML 快照", !("pageHtml" in p));
  check("bridge 字段已带上", !!picked && typeof picked.bridge === "string", picked && picked.bridge);

  console.log("\n[4b] 层级、重选与失效元素");
  function key(k) { document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); }
  fire({ type: "start-pick", sessionId: "test-session" });
  pointTarget = $("#login-btn"); mouse("mousemove", document);
  key("ArrowUp");
  check("上键选择父元素", /<header>/.test(ov.shadowRoot.querySelector(".ov-tip").textContent));
  key("ArrowDown");
  check("下键返回原子元素", /login-btn/.test(ov.shadowRoot.querySelector(".ov-tip").textContent));
  sent.length = 0;
  mouse("click", pointTarget, { ctrlKey: true, button: 2 });
  check("右键不能锁定", !ov.shadowRoot.querySelector(".ov-review"));
  mouse("click", pointTarget, { ctrlKey: true });
  check("框架锁定向后台请求仲裁", sent.some((m) => m.type === "pick-lock" && m.sessionId === "test-session"));
  ov.shadowRoot.querySelector('[data-action="retry"]').click();
  check("重选通知其它框架恢复", sent.some((m) => m.type === "pick-resume"));
  check("重选收起确认卡片", !ov.shadowRoot.querySelector(".ov-review"));
  mouse("mousemove", document); mouse("click", pointTarget, { ctrlKey: true });
  const detached = pointTarget;
  const parent = detached.parentElement;
  detached.remove();
  key("Enter");
  check("DOM已删除时不回传", !sent.some((m) => m.type === "picked"));
  check("DOM失效提示明确", /已被页面移除/.test(ov.shadowRoot.querySelector(".ov-review").textContent));
  parent.appendChild(detached);
  key("Escape");
  check("Esc携带会话ID通知全局取消", sent.some((m) => m.type === "picked-status" && m.sessionId === "test-session"));
  check("取消清理确认卡片", !ov.shadowRoot.querySelector(".ov-review"));

  console.log("\n[5] Esc 取消 / stop-pick");
  fire({ type: "start-pick", hint: "x" });
  await tick();
  check("重新进入拾取", !!ov.shadowRoot.querySelector(".ov-bar"));
  dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  await tick();
  check("Esc 结束拾取", !ov.shadowRoot.querySelector(".ov-bar"));

  fire({ type: "start-pick", hint: "x" });
  await tick();
  const r2 = fire({ type: "stop-pick" });
  await tick();
  check("stop-pick 生效", !!r2 && r2.ok === true && !ov.shadowRoot.querySelector(".ov-bar"));

  console.log("\n[6] 面板内手动拾取仍可用");
  const r3 = fire({ type: "toggle-panel" });
  await tick();
  check("面板可挂载", !!dom.window.document.getElementById(Engine.UI_HOST_ID || Engine.UI_ROOT_ID));
  check("面板可见", Panel.isVisible());
  const r4 = fire({ type: "toggle-picker" });
  await tick();
  check("面板按钮可进入拾取", !!r4 && r4.picking === true);
  fire({ type: "toggle-picker" });
  await tick();

  console.log("\n[7] 桌面实时 XPath 校验与高亮清理");
  const live = fire({ type: "browser-validate", action: "validate", xpath: "//button" });
  check("校验实际 DOM 的多节点", live && live.ok && live.count === 2 && live.highlighted === 2);
  check("返回可序列化摘要而非 DOM 对象", live && JSON.stringify(live) && !live.matches[0].node);
  const zero = fire({ type: "browser-validate", action: "validate", xpath: "//does-not-exist" });
  check("零匹配校验成功", zero && zero.valid && zero.count === 0 && zero.highlighted === 0);
  const invalid = fire({ type: "browser-validate", action: "validate", xpath: "//*[" });
  check("非法表达式返回明确错误", invalid && !invalid.valid && !!invalid.error);
  const value = fire({ type: "browser-validate", action: "validate", xpath: "count(//button)" });
  check("数字 XPath 返回值且不高亮", value && value.matches[0].value === "2" && value.highlighted === 0);
  const clear = fire({ type: "browser-validate", action: "clear" });
  check("清空指令确认", clear && clear.ok && clear.cleared);
  check("覆盖层未遗留高亮框", !ov.shadowRoot.querySelector(".ov-hl"));

  console.log("\n" + "=".repeat(62));
  if (fails.length) {
    console.log(` 结果：${pass} 通过 / ${fails.length} 失败 ❌`);
    process.exit(1);
  }
  console.log(` 结果：全部 ${pass} 项通过 ✅`);
  // 内容脚本会留下跟随滚动的高亮定时器（浏览器里是预期行为），测试需显式退出
  process.exit(0);
})();
