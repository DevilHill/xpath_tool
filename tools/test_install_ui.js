/* 在 Node + jsdom 中真实加载桌面版前端，验证「一键安装扩展」弹窗：
 * 入口按钮、浏览器列表渲染、推荐策略标记、安装请求体、结果/兜底渲染、状态指示。
 *
 * 用法：node tools/test_install_ui.js
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

/* confirm 桩：默认确认；可切换为取消，并记录被问到的文案 */
let confirmAnswer = true;
const confirmCalls = [];
try {
  dom.window.confirm = (msg) => { confirmCalls.push(String(msg)); return confirmAnswer; };
} catch (e) { /* 忽略 */ }

/* ---------------- fetch 桩 ---------------- */
const calls = [];
let browsersPayload = {
  ok: true, recommendKey: "chrome", extDir: "D:\\App\\XPathStudio\\extension",
  dirError: "", port: 8790, platform: "Windows", connected: 0,
  stats: { clients: 1, extensions: 0, uis: 1 },
  browsers: [
    { key: "chrome", name: "Google Chrome", path: "C:/x/chrome.exe", version: "153.0.8010.53", major: 153,
      branded: true, cdp: true, flag: false, recommend: "guided",
      note: "当前 Chrome 需在扩展页手动加载" },
    { key: "edge", name: "Microsoft Edge", path: "C:/x/msedge.exe", version: "154.0.4258.37", major: 154,
      branded: false, cdp: true, flag: true, recommend: "guided", note: "" },
  ],
};
let installResponse = { ok: true, strategy: "guided", browser: "Google Chrome", browserKey: "chrome",
  version: "153.0.8010.53", extDir: browsersPayload.extDir, guided: true, target: "existing",
  installationVerified: false, steps: ["打开开发者模式", "加载已解压的扩展程序"],
  stats: { clients: 1, extensions: 0, uis: 1 } };
let healthPayload = { ok: true, version: "1.0", bridge: { clients: 2, extensions: 1, uis: 1, lastPickAt: 0 } };
// 企业策略状态（未安装时带副作用说明；安装后带 extId / policyPath）
let policyPayload = { ok: true, supported: true, installed: false, extId: "", policyPath: "", mine: [] };
let policyRemovePayload = { ok: true, steps: ["已移除策略条目", "请完全退出浏览器后重新打开"] };

function fakeFetch(url, opts) {
  const p = String(url);
  const method = (opts && opts.method) || "GET";
  calls.push({ path: p, method, body: opts && opts.body ? JSON.parse(opts.body) : null });
  let payload = { ok: true };
  if (p.includes("/api/config")) payload = { ok: true, config: { configured: false } };
  else if (p.includes("/api/parse")) payload = { ok: true, token: "t1", count: 1, desc: { top: [["html", 1]] }, tree: { idx: 0, tag: "html", attrs: {}, text: "", children: [] } };
  else if (p.includes("/api/extension/browsers")) payload = browsersPayload;
  else if (p.includes("/api/extension/install")) payload = installResponse;
  else if (p.includes("/api/extension/policy-status")) payload = policyPayload;
  else if (p.includes("/api/extension/policy-remove")) payload = policyRemovePayload;
  else if (p.includes("/api/extension/open-folder")) payload = { ok: true, path: browsersPayload.extDir };
  else if (p.includes("/api/health")) payload = healthPayload;
  else if (p.includes("/api/bridge/pick")) payload = { ok: false, error: "没有已连接的浏览器扩展。" };
  else if (p.includes("/api/validate")) payload = { ok: true, valid: true, count: 1, matches: [] };
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
}
global.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

/* ---------------- WebSocket 桩 ---------------- */
const sockets = [];
class FakeWS {
  constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
  send(d) { this.sent.push(d); }
  close() { this.readyState = 3; if (this.onclose) this.onclose(); }
  _open() { this.readyState = 1; if (this.onopen) this.onopen(); }
  _msg(o) { if (this.onmessage) this.onmessage({ data: JSON.stringify(o) }); }
}
global.WebSocket = FakeWS;
dom.window.WebSocket = FakeWS;

/* ---------------- 断言工具 ---------------- */
let pass = 0;
const fails = [];
function check(name, cond, detail) {
  if (cond) { pass++; console.log(`  [OK]   ${name}`); }
  else { fails.push(name); console.log(`  [FAIL] ${name}` + (detail ? `  -> ${detail}` : "")); }
}
const $ = (s) => dom.window.document.querySelector(s);
const $$ = (s) => Array.from(dom.window.document.querySelectorAll(s));
const tick = (n = 3) => new Promise((r) => {
  let i = 0;
  const step = () => (++i >= n ? r() : setTimeout(step, 0));
  setTimeout(step, 0);
});

(async () => {
  console.log("=".repeat(62));
  console.log(" XPath Studio · 一键安装扩展 UI 测试（jsdom）");
  console.log("=".repeat(62));

  // 手动执行 app.js（IIFE 会立刻绑定事件）
  try {
    new Function(APP_SRC)();
  } catch (e) {
    console.log("  app.js 执行异常：" + e.message);
    process.exit(1);
  }
  await tick(5);

  const ws = sockets[0];
  check("已建立 WebSocket", !!ws);
  ws._open();
  ws._msg({ type: "hello", server: "XPathStudio", version: "1.0", stats: { extensions: 0 } });
  await tick();

  console.log("\n[1] 入口与初始状态");
  check("顶栏 chip 是可点击按钮", $("#bridgeChip").tagName === "BUTTON", $("#bridgeChip").tagName);
  check("安装弹窗默认隐藏", $("#installModal").hidden === true);
  check("抓取面板的安装提示默认可见（未连扩展）", $("#grabInstall").hidden === false);
  check("存在「一键安装扩展」内联按钮", !!$("#btnInstallExtInline"));
  ws._msg({ type: "stats", stats: { extensions: 1, clients: 2, uis: 1 } });
  await tick();
  check("扩展连上后隐藏安装提示", $("#grabInstall").hidden === true);
  check("扩展连上后 chip 变绿", $("#bridgeChip").classList.contains("on"));
  ws._msg({ type: "stats", stats: { extensions: 0, clients: 1, uis: 1 } });
  await tick();
  check("扩展断开后重新显示安装提示", $("#grabInstall").hidden === false);

  console.log("\n[2] 打开弹窗：拉取浏览器列表");
  calls.length = 0;
  $("#bridgeChip").click();
  await tick(6);
  check("弹窗已打开", $("#installModal").hidden === false);
  check("以 GET 请求 /api/extension/browsers",
    calls.some((c) => c.path.includes("/api/extension/browsers") && c.method === "GET"),
    JSON.stringify(calls.map((c) => c.method + " " + c.path)));

  const items = $$(".browser-item");
  check("渲染出 2 个浏览器条目", items.length === 2, String(items.length));
  check("显示浏览器名称", /Google Chrome/.test($("#installBrowsers").textContent));
  check("显示版本号", /153\.0\.8010\.53/.test($("#installBrowsers").textContent));
  check("Chrome 被标记为推荐", $$(".browser-tag.rec").length === 1, String($$(".browser-tag.rec").length));
  check("推荐现有浏览器的引导安装", /推荐：引导安装/.test($(".browser-tag.rec").textContent), $(".browser-tag.rec").textContent);
  check("主按钮明确安装位置", $("#btnInstallRun").textContent === "安装到现有浏览器");
  check("默认界面展示手动加载说明", /加载已解压的扩展程序/.test($("#installTargetHint").textContent));
  check("默认选中推荐浏览器（Chrome）",
    ($$('input[name="installBrowser"]').find((r) => r.checked) || {}).value === "chrome",
    JSON.stringify($$('input[name="installBrowser"]').map((r) => r.value + ":" + r.checked)));
  check("扩展目录填入只读输入框", $("#installPath").value === browsersPayload.extDir, $("#installPath").value);
  check("状态条提示现有 Chrome", /现有 Google Chrome/.test($("#installState").textContent), $("#installState").textContent);

  console.log("\n[3] 一键安装：请求体与结果渲染");
  calls.length = 0;
  $("#btnInstallRun").click();
  await tick(8);
  const inst = calls.find((c) => c.path.includes("/api/extension/install"));
  check("发起了安装请求", !!inst);
  check("请求体带 strategy=auto", inst && inst.body && inst.body.strategy === "auto", JSON.stringify(inst && inst.body));
  check("请求体带选中的浏览器 key", inst && inst.body && inst.body.browser === "chrome", JSON.stringify(inst && inst.body));
  check("结果区要求完成加载而非假报安装完成", /请在现有浏览器完成加载/.test($("#installResult").textContent) && !/安装完成/.test($("#installResult").textContent), $("#installResult").textContent);
  check("结果区显示安装方式", /引导安装/.test($("#installResult").textContent));
  check("结果区显示扩展目录", $("#installResult").textContent.includes(browsersPayload.extDir));
  check("尚未加载时状态条为 warn", $("#installState").classList.contains("warn"), $("#installState").className);
  check("结果样式为待完成", !!$("#installResult .res-box.warn"));
  check("有复制扩展目录按钮", /复制扩展目录路径/.test($("#installResult").textContent));

  console.log("\n[4] 切换到 Chrome 后重装（推荐 CDP）");
  const chromeRadio = $$('input[name="installBrowser"]').find((r) => r.value === "chrome");
  chromeRadio.checked = true;
  chromeRadio.dispatchEvent(new dom.window.Event("change"));
  await tick(3);
  check("选中态跟随切换", $$(".browser-item.sel").length === 1);
  calls.length = 0;
  $("#installAdv").checked = true;
  $("#installAdv").dispatchEvent(new dom.window.Event("change"));
  const cdpRadio = $('input[name="installStrategy"][value="cdp"]');
  cdpRadio.checked = true;
  cdpRadio.dispatchEvent(new dom.window.Event("change"));
  check("显式 CDP 时按钮说明独立实例", $("#btnInstallRun").textContent === "启动独立实例");
  installResponse = { ok: true, strategy: "cdp", method: "Extensions.loadUnpacked",
    browser: "Google Chrome", browserKey: "chrome", version: "153.0.8010.53",
    extDir: browsersPayload.extDir, connected: false,
    warning: "浏览器已启动，但扩展尚未连回桌面版。", fallback: "guided" };
  $("#btnInstallRun").click();
  await tick(8);
  const inst2 = calls.find((c) => c.path.includes("/api/extension/install"));
  check("只有显式选 CDP 才发出独立安装请求", inst2 && inst2.body.strategy === "cdp");
  check("第二次安装带上 chrome", inst2 && inst2.body && inst2.body.browser === "chrome", JSON.stringify(inst2 && inst2.body));
  check("CDP 方式被展示", /调试端口/.test($("#installResult").textContent), $("#installResult").textContent);
  check("具体方法名被展示", /Extensions\.loadUnpacked/.test($("#installResult").textContent));
  check("未连回时显示警告样式", !!$("#installResult .res-box.warn"));
  check("未连回时状态条为 warn", $("#installState").classList.contains("warn"), $("#installState").className);
  check("提供「改用引导安装」兜底按钮", /改用引导安装/.test($("#installResult").textContent));

  console.log("\n[5] 兜底按钮 -> 引导安装");
  calls.length = 0;
  const fbBtn = $$("#installResult button").find((b) => /引导安装/.test(b.textContent));
  fbBtn.click();
  await tick(8);
  const inst3 = calls.find((c) => c.path.includes("/api/extension/install"));
  check("兜底按钮发出 strategy=guided", inst3 && inst3.body && inst3.body.strategy === "guided", JSON.stringify(inst3 && inst3.body));

  installResponse = { ok: true, guided: true, copied: true, path: browsersPayload.extDir,
    strategy: "guided", browser: "Google Chrome", browserKey: "chrome", version: "153.0.8010.53",
    extDir: browsersPayload.extDir,
    steps: ["已打开浏览器的扩展管理页", "打开右上角「开发者模式」", "点「加载已解压的扩展程序」", "粘贴目录"] };
  $("#btnInstallGuided").click();
  await tick(8);
  check("引导安装渲染出步骤列表", $$("#installResult li").length === 4, String($$("#installResult li").length));
  check("步骤文案正确", /开发者模式/.test($("#installResult").textContent));
  check("引导安装不算「已连接」", /请在现有浏览器完成加载/.test($("#installResult").textContent), $("#installResult").textContent);

  console.log("\n[6] 高级选项与目录操作");
  $("#installAdv").checked = false;
  $("#installAdv").dispatchEvent(new dom.window.Event("change"));
  check("收起高级选项恢复现有浏览器安装", $('input[name="installStrategy"]:checked').value === "auto" && $("#btnInstallRun").textContent === "安装到现有浏览器");
  $("#installAdv").checked = true;
  $("#installAdv").dispatchEvent(new dom.window.Event("change"));
  await tick();
  check("高级选项展开", $("#installAdvBody").hidden === false);
  check("有 5 种安装方式可选", $$('input[name="installStrategy"]').length === 5,
    String($$('input[name="installStrategy"]').length));
  check("默认选中 auto", ($$('input[name="installStrategy"]').find((r) => r.checked) || {}).value === "auto");
  const strategies = $$('input[name="installStrategy"]').map((r) => r.value).sort();
  check("包含企业策略选项", strategies.includes("policy"), strategies.join(","));

  console.log("\n[6b] 企业策略方式");
  const policyRadio = $$('input[name="installStrategy"]').find((r) => r.value === "policy");
  policyRadio.checked = true;
  policyRadio.dispatchEvent(new dom.window.Event("change"));
  await tick(8);
  check("选中策略后展开策略面板", $("#policyField").hidden === false);
  check("策略提示说明装进现有浏览器", /现有浏览器/.test($("#strategyHint").textContent),
    $("#strategyHint").textContent);
  check("查询策略状态请求已发出",
    calls.some((c) => c.path.includes("/api/extension/policy-status") && c.method === "POST"));
  check("未安装时列出副作用", /由贵单位管理/.test($("#policyBox").textContent), $("#policyBox").textContent);
  check("未安装时隐藏卸载按钮", $("#btnRemovePolicy").hidden === true);
  check("提示需完全退出浏览器", /完全退出浏览器/.test($("#policyBox").textContent));

  // 已安装状态
  policyPayload = { ok: true, supported: true, installed: true,
    extId: "kkienpkecmpnmgfedaclnegnoemniehp",
    policyPath: "HKCU\\Software\\Policies\\Microsoft\\Edge\\ExtensionInstallForcelist",
    mine: ["kkienpkecmpnmgfedaclnegnoemniehp;http://127.0.0.1:8790/extension/update.xml"] };
  policyRadio.checked = false;
  policyRadio.checked = true;
  policyRadio.dispatchEvent(new dom.window.Event("change"));
  await tick(8);
  check("已安装时显示扩展 ID", /kkienpkecmpnmgfedaclnegnoemniehp/.test($("#policyBox").textContent),
    $("#policyBox").textContent);
  check("已安装时显示策略位置", /ExtensionInstallForcelist/.test($("#policyBox").textContent));
  check("已安装时出现卸载按钮", $("#btnRemovePolicy").hidden === false);

  // 不支持的平台
  policyPayload = { ok: true, supported: false, installed: false, reason: "仅支持 Windows" };
  policyRadio.checked = false;
  policyRadio.checked = true;
  policyRadio.dispatchEvent(new dom.window.Event("change"));
  await tick(8);
  check("不支持平台时给出原因", /仅支持 Windows/.test($("#policyBox").textContent), $("#policyBox").textContent);

  // 卸载策略
  policyPayload = { ok: true, supported: true, installed: true,
    extId: "kkienpkecmpnmgfedaclnegnoemniehp", policyPath: "HKCU\\...", mine: [] };
  policyRadio.checked = false;
  policyRadio.checked = true;
  policyRadio.dispatchEvent(new dom.window.Event("change"));
  await tick(8);
  calls.length = 0;
  $("#btnRemovePolicy").click();
  await tick(10);
  check("卸载策略调用后端接口",
    calls.some((c) => c.path.includes("/api/extension/policy-remove") && c.method === "POST"),
    JSON.stringify(calls.map((c) => c.path)));
  check("卸载结果渲染到结果区", /已移除策略/.test($("#installResult").textContent),
    $("#installResult").textContent);
  check("卸载后状态提示为已移除", /已移除本扩展的策略条目/.test($("#installState").textContent),
    $("#installState").textContent);
  policyRemovePayload = { ok: true, steps: ["已移除策略条目", "请完全退出浏览器后重新打开"] };

  // 切回 auto，策略面板应收回
  const autoRadio = $$('input[name="installStrategy"]').find((r) => r.value === "auto");
  autoRadio.checked = true;
  autoRadio.dispatchEvent(new dom.window.Event("change"));
  await tick(4);
  check("切回 auto 后收起策略面板", $("#policyField").hidden === true);

  calls.length = 0;
  $("#btnOpenExtDir").click();
  await tick(5);
  check("打开目录调用后端接口", calls.some((c) => c.path.includes("/api/extension/open-folder")));

  copied.length = 0;
  $("#btnCopyExtDir").click();
  await tick(3);
  check("复制目录写入剪贴板", copied[copied.length - 1] === browsersPayload.extDir, String(copied[copied.length - 1]));

  console.log("\n[6c] 企业策略安装：确认对话框 / 失败诊断 / 兜底");
  const policyRadio2 = $$('input[name="installStrategy"]').find((r) => r.value === "policy");
  policyPayload = { ok: true, supported: true, policyConfigured: false, installed: false,
    extId: "", policyPath: "", mine: [] };
  policyRadio2.checked = true;
  policyRadio2.dispatchEvent(new dom.window.Event("change"));
  await tick(8);

  // 取消确认：不应发出安装请求
  confirmAnswer = false;
  confirmCalls.length = 0;
  calls.length = 0;
  $("#btnInstallRun").click();
  await tick(6);
  check("策略安装前弹出确认对话框", confirmCalls.length === 1, String(confirmCalls.length));
  check("确认文案提示可能被安全策略/设备管理拒绝",
    /安全限制|设备管理/.test(confirmCalls[0] || ""), confirmCalls[0]);
  check("确认文案提示写入成功≠已安装",
    /不代表扩展已安装|不代表安装成功/.test(confirmCalls[0] || ""), confirmCalls[0]);
  check("取消确认后不发出安装请求",
    !calls.some((c) => c.path.includes("/api/extension/install")),
    JSON.stringify(calls.map((c) => c.path)));

  // 确认：返回「注册表写入失败」，验证诊断渲染与兜底
  confirmAnswer = true;
  calls.length = 0;
  installResponse = {
    ok: false, strategy: "policy", browser: "Google Chrome", browserKey: "chrome",
    version: "153.0.8010.53", stage: "policy-write",
    extId: "kkienpkecmpnmgfedaclnegnoemniehp",
    policyPath: "HKCU\\Software\\Policies\\Google\\Chrome\\ExtensionInstallForcelist",
    extDir: browsersPayload.extDir, connected: false, fallback: "guided",
    policyConfigured: false, installationVerified: false, needsRestart: false,
    error: "写入注册表失败：HKCU\\Software\\Policies\\Google\\Chrome\\ExtensionInstallForcelist",
    diagnostics: { stage: "policy-write", errorType: "PermissionError",
      systemError: "[WinError 5] 拒绝访问。", winerror: 5 },
  };
  $("#btnInstallRun").click();
  await tick(8);
  const instP = calls.filter((c) => c.path.includes("/api/extension/install")).pop();
  check("确认后发出 strategy=policy 请求",
    instP && instP.body && instP.body.strategy === "policy", JSON.stringify(instP && instP.body));
  check("失败结果显示「安装失败」标题",
    /安装失败/.test($("#installResult").textContent), $("#installResult").textContent);
  check("失败结果展示执行阶段",
    /执行阶段：policy-write/.test($("#installResult").textContent), $("#installResult").textContent);
  check("失败结果展示系统错误类型",
    /PermissionError/.test($("#installResult").textContent), $("#installResult").textContent);
  check("失败结果展示 Windows 错误码",
    /错误码 5/.test($("#installResult").textContent), $("#installResult").textContent);
  check("失败结果样式为错误", !!$("#installResult .res-box.err"));
  check("失败时不显示「已连接」",
    !/安装完成/.test($("#installResult").textContent), $("#installResult").textContent);
  check("失败时提供引导安装兜底按钮",
    /改用引导安装/.test($("#installResult").textContent));
  check("失败时状态条为 err",
    $("#installState").classList.contains("err"), $("#installState").className);

  copied.length = 0;
  const diagBtn = $$("#installResult button").find((b) => /复制安装诊断/.test(b.textContent));
  check("存在「复制安装诊断」按钮", !!diagBtn);
  diagBtn.click();
  await tick(3);
  let diag = null;
  try { diag = JSON.parse(copied[copied.length - 1]); } catch (e) { /* 保持 null */ }
  check("诊断 JSON 含 stage 与 winerror",
    !!diag && diag.stage === "policy-write" && diag.diagnostics && diag.diagnostics.winerror === 5,
    copied[copied.length - 1]);
  check("诊断 JSON 标记「配置未写入 / 安装未验证」",
    !!diag && diag.policyConfigured === false && diag.installationVerified === false,
    copied[copied.length - 1]);
  check("诊断 JSON 含扩展目录与策略位置",
    !!diag && !!diag.extDir && /ExtensionInstallForcelist/.test(diag.policyPath || ""),
    copied[copied.length - 1]);

  console.log("\n[6d] 策略配置存在 ≠ 扩展已安装");
  policyPayload = { ok: true, supported: true, policyConfigured: true, installed: true,
    extId: "kkienpkecmpnmgfedaclnegnoemniehp",
    policyPath: "HKCU\\Software\\Policies\\Google\\Chrome\\ExtensionInstallForcelist",
    mine: ["kkienpkecmpnmgfedaclnegnoemniehp;http://127.0.0.1:8790/extension/update.xml"] };
  policyRadio2.checked = false;
  policyRadio2.checked = true;
  policyRadio2.dispatchEvent(new dom.window.Event("change"));
  await tick(8);
  check("策略存在时标题说明不代表已安装",
    /不代表扩展已安装/.test($("#policyBox").textContent), $("#policyBox").textContent);
  check("策略存在时提示去扩展管理页核对实际状态",
    /扩展管理页检查实际安装状态/.test($("#policyBox").textContent), $("#policyBox").textContent);
  check("策略存在时显示卸载按钮", $("#btnRemovePolicy").hidden === false);

  console.log("\n[6e] 切换浏览器时刷新策略状态（防止旧响应覆盖）");
  calls.length = 0;
  policyPayload = { ok: true, supported: true, policyConfigured: false, installed: false, extId: "", policyPath: "", mine: [] };
  const edgeRadio2 = $$('input[name="installBrowser"]').find((r) => r.value === "edge");
  edgeRadio2.checked = true;
  edgeRadio2.dispatchEvent(new dom.window.Event("change"));
  await tick(8);
  const statusCalls = calls.filter((c) => c.path.includes("/api/extension/policy-status"));
  check("切换浏览器后重新查询策略状态", statusCalls.length >= 1,
    JSON.stringify(calls.map((c) => c.method + " " + c.path)));
  check("查询使用切换后的浏览器 key",
    statusCalls.length >= 1 && statusCalls[statusCalls.length - 1].body.browser === "edge",
    JSON.stringify(statusCalls.map((c) => c.body)));
  // 切回 auto，避免影响后续小节
  const autoRadio2 = $$('input[name="installStrategy"]').find((r) => r.value === "auto");
  autoRadio2.checked = true;
  autoRadio2.dispatchEvent(new dom.window.Event("change"));
  await tick(4);

  console.log("\n[7] 重新检测连接");
  healthPayload = { ok: true, version: "1.0", bridge: { clients: 3, extensions: 2, uis: 2, lastPickAt: 0 } };
  $("#btnRecheckBridge").click();
  await tick(6);
  check("重新检测显示连接数量并提示核对浏览器", /扩展连接（2 个）/.test($("#installState").textContent) && /目标浏览器/.test($("#installState").textContent), $("#installState").textContent);
  healthPayload = { ok: true, version: "1.0", bridge: { clients: 1, extensions: 0, uis: 1, lastPickAt: 0 } };
  $("#btnRecheckBridge").click();
  await tick(6);
  check("无扩展时给出提示", /还没有扩展连上来/.test($("#installState").textContent), $("#installState").textContent);

  console.log("\n[8] 关闭方式");
  $("#btnCloseInstall").click();
  await tick();
  check("X 按钮关闭弹窗", $("#installModal").hidden === true);
  $("#bridgeChip").click();
  await tick(4);
  check("再次打开成功", $("#installModal").hidden === false);
  $("#installModal").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await tick();
  check("点遮罩关闭弹窗", $("#installModal").hidden === true);
  $("#bridgeChip").click();
  await tick(4);
  dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape" }));
  await tick();
  check("Esc 关闭弹窗", $("#installModal").hidden === true);

  console.log("\n[9] 无浏览器可用的降级");
  browsersPayload = { ok: true, recommendKey: "", extDir: "", dirError: "找不到扩展目录（extension/）", port: 8790,
    platform: "Windows", connected: 0, browsers: [], stats: {} };
  $("#bridgeChip").click();
  await tick(6);
  check("无浏览器时给出说明", /没有检测到/.test($("#installBrowsers").textContent), $("#installBrowsers").textContent);
  check("状态条提示未检测到", $("#installState").classList.contains("warn"), $("#installState").className);
  check("目录缺失时展示错误文本", /找不到扩展目录/.test($("#installPath").value), $("#installPath").value);

  console.log("\n" + "=".repeat(62));
  if (fails.length) {
    console.log(` 结果：${pass} 通过 / ${fails.length} 失败 ❌`);
    fails.forEach((f) => console.log("   - " + f));
    process.exit(1);
  }
  console.log(` 结果：全部 ${pass} 项通过 ✅`);
})();
