/* ============================================================
 * XPath Studio · 后台 Service Worker（MV3）
 *  - 工具栏图标 / 快捷键 -> 开关页面面板
 *  - 与本地桌面版建立 WebSocket 长连接（双向实时桥接）
 *      桌面版「抓取元素」 --start-pick--> 扩展 -> 内容脚本进入拾取模式
 *      内容脚本 Ctrl+左键选中 --picked--> 扩展 -> 桌面版渲染定位器
 *  - 代理对本地桌面版的 AI 请求（service worker 不受页面 CORS 限制）
 * ============================================================ */
"use strict";

var DEFAULT_BRIDGE = "http://127.0.0.1:8790";
// 每次后台启动分配独立身份，避免不同浏览器的 tabId / frameId 碰撞。
var browserId = crypto.randomUUID();
var lastTarget = null;

function joinUrl(base, path) {
  var b = (base || DEFAULT_BRIDGE).trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(b)) b = "http://" + b;
  return b + path;
}

/* 哪些页面根本不允许扩展注入 —— 提前拦掉并给出人话解释，
   而不是把 Chrome 的原始报错（Cannot access contents of the page…）直接抛给用户 */
function injectBlockedReason(url) {
  if (!url) return ""; // 拿不到地址就乐观放行，交给后续错误分支
  var scheme = String(url.split(":")[0] || "").toLowerCase();
  if (scheme === "chrome" || scheme === "edge" || scheme === "about" ||
      scheme === "devtools" || scheme === "chrome-extension" ||
      scheme === "edge-extension" || scheme === "brave" || scheme === "view-source") {
    return "这是浏览器内置页面（" + scheme + "://），不允许扩展注入。请切到普通网页（http/https）后再抓取。";
  }
  if (/^https?:\/\/(chromewebstore\.google\.com|chrome\.google\.com\/webstore|microsoftedge\.microsoft\.com\/addons)/i.test(url)) {
    return "扩展商店页面禁止扩展注入，请切到普通网页后再抓取。";
  }
  if (scheme === "file") {
    return "本地文件页面需要先在扩展详情里打开「允许访问文件网址」，否则无法抓取。";
  }
  return "";
}

function isInjectable(url) {
  // 有了 tabs 权限后 url 一般都能拿到；拿不到时乐观放行，交给错误分支处理
  if (!url) return true;
  return !injectBlockedReason(url) && /^(https?|file):/i.test(url);
}

/* 把 Chrome 的原始报错翻译成人话，别让用户看到 manifest 术语。
   注意判断顺序：「Cannot access contents of url "about:blank"…must request permission
   to access this host」里**也**含 "must request permission to access"，所以更具体的
   url 分支必须先判，否则会被通用分支吃掉。 */
function friendlyInjectError(msg) {
  var s = String(msg || "");
  if (s.indexOf("Cannot access contents of url") >= 0) {
    return "该页面不允许扩展注入（可能是 about:blank 或浏览器内置页面）。请切到普通网页后再抓取。";
  }
  if (s.indexOf("Cannot access contents of the page") >= 0 ||
      s.indexOf("must request permission to access") >= 0) {
    return "扩展没有该页面的访问权限（manifest 的 host_permissions 不足）。请在扩展管理页重新加载扩展后再试。";
  }
  if (s.indexOf("Receiving end does not exist") >= 0) {
    return "内容脚本还没注入（页面可能在扩展安装前就已打开）。刷新页面后重试即可。";
  }
  return s;
}

async function sendToTab(tabId, msg, url, frameId) {
  var blocked = injectBlockedReason(url);
  if (blocked) return { ok: false, error: blocked };
  var options = { frameId: frameId == null ? 0 : frameId };
  try {
    return await chrome.tabs.sendMessage(tabId, msg, options);
  } catch (e) {
    // 内容脚本可能尚未注入（例如扩展刚安装、页面是安装前打开的）
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tabId, frameIds: [options.frameId] },
        files: ["lib/engine.js", "ui.js", "content.js"]
      });
      return await chrome.tabs.sendMessage(tabId, msg, options);
    } catch (e2) {
      return { ok: false, error: friendlyInjectError((e2 && e2.message) || e2) };
    }
  }
}

async function setBadge(text, color) {
  try {
    await chrome.action.setBadgeText({ text: text || "" });
    if (color) await chrome.action.setBadgeBackgroundColor({ color: color });
  } catch (e) { /* 忽略 */ }
}

async function flashBadge(text) {
  await setBadge(text, "#6366f1");
  setTimeout(function () { chrome.action.setBadgeText({ text: "" }); }, 1800);
}

async function activeTab() {
  var tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tabs || !tabs.length) tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs && tabs[0];
}

/* 抓取会话固定到启动时的标签页；不要用取消时的活动标签页代替。 */
var pickSession = null;
var pickSerial = 0;
var pickRequest = 0;

async function stopPickSession() {
  pickRequest++;
  var session = pickSession;
  pickSession = null;
  if (!session) return;
  await Promise.all(session.frames.map(async function (f) {
    try {
      await chrome.tabs.sendMessage(session.tabId,
        { type: "stop-pick", sessionId: session.id }, { frameId: f.frameId });
    } catch (e) { /* 导航或关闭的框架无需补注入 */ }
  }));
}

async function startPickSession(tab, hint) {
  var stopping = stopPickSession();
  var request = pickRequest;
  await stopping;
  var frames = await chrome.webNavigation.getAllFrames({ tabId: tab.id });
  if (request !== pickRequest) return { ok: false, error: "本次抓取已取消或被替换" };
  frames = frames || [{ frameId: 0, parentFrameId: -1, url: tab.url }];
  var session = { id: "pick-" + Date.now() + "-" + (++pickSerial), tabId: tab.id,
    topUrl: tab.url, frames: frames, ownerFrame: null };
  pickSession = session;
  var results = await Promise.all(frames.map(async function (f) {
    // about:blank/srcdoc 继承宿主授权；交给浏览器决定，不绕过权限检查。
    var url = /^about:(blank|srcdoc)/.test(f.url || "") ? "" : f.url;
    var res = await sendToTab(tab.id,
      { type: "start-pick", hint: hint, sessionId: session.id }, url, f.frameId);
    if (pickSession !== session) {
      try { await chrome.tabs.sendMessage(tab.id,
        { type: "stop-pick", sessionId: session.id }, { frameId: f.frameId }); } catch (e) {}
    }
    return res;
  }));
  var count = results.filter(function (r) { return r && r.ok; }).length;
  if (!count && pickSession === session) pickSession = null;
  return { ok: count > 0, frameCount: count, skippedFrames: frames.length - count,
    error: count ? "" : ((results[0] || {}).error || "页面未就绪，请刷新后重试") };
}

function isPickSender(msg, sender) {
  return !!(pickSession && sender.tab && sender.tab.id === pickSession.tabId &&
    msg.sessionId === pickSession.id);
}

async function lockPickFrame(msg, sender) {
  if (!isPickSender(msg, sender)) return { ok: false, error: "抓取会话已结束，请重新抓取" };
  var session = pickSession;
  if (session.ownerFrame != null && session.ownerFrame !== sender.frameId)
    return { ok: false, error: "另一个框架已有待确认元素" };
  session.ownerFrame = sender.frameId;
  await Promise.all(session.frames.filter(function (f) { return f.frameId !== sender.frameId; })
    .map(async function (f) {
      try { await chrome.tabs.sendMessage(session.tabId,
        { type: "pause-pick", sessionId: session.id }, { frameId: f.frameId }); } catch (e) {}
    }));
  return { ok: pickSession === session };
}

async function resumePickFrames(msg, sender) {
  if (!isPickSender(msg, sender) || pickSession.ownerFrame !== sender.frameId)
    return { ok: false, error: "抓取会话已结束" };
  var session = pickSession;
  session.ownerFrame = null;
  await Promise.all(session.frames.map(async function (f) {
    try { await chrome.tabs.sendMessage(session.tabId,
      { type: "resume-pick", sessionId: session.id }, { frameId: f.frameId }); } catch (e) {}
  }));
  return { ok: true };
}

/* ---------------- 工具栏图标 ---------------- */
chrome.action.onClicked.addListener(async function (tab) {
  if (!tab || !tab.id) return;
  if (!isInjectable(tab.url)) {
    flashBadge("✕");
    return;
  }
  var res = await sendToTab(tab.id, { type: "toggle-panel" }, tab.url);
  if (!res || !res.ok) flashBadge("✕");
});

/* ---------------- 快捷键 ---------------- */
chrome.commands.onCommand.addListener(async function (command) {
  var tab = await activeTab();
  if (!tab || !tab.id || !isInjectable(tab.url)) {
    flashBadge("✕");
    return;
  }
  if (command === "toggle-panel") await sendToTab(tab.id, { type: "toggle-panel" }, tab.url);
  else if (command === "toggle-picker") await sendToTab(tab.id, { type: "toggle-picker" }, tab.url);
});

/* ============================================================
 * 与桌面版的 WebSocket 长连接
 * ============================================================ */
var ws = null;
var wsUrl = null;
var wsRetry = 0;
var wsTimer = null;
var bridgeBase = DEFAULT_BRIDGE;

function toWsUrl(base) {
  var b = (base || DEFAULT_BRIDGE).trim().replace(/\/+$/, "");
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(b)) b = "http://" + b;
  return b.replace(/^http/i, "ws") + "/ws";
}

function bridgeState() {
  var st = ws ? ws.readyState : 3; // 0 连接中 1 已连接 2 关闭中 3 已关闭
  return {
    connected: st === 1,
    connecting: st === 0,
    url: wsUrl || toWsUrl(bridgeBase)
  };
}

function wsSend(obj) {
  if (ws && ws.readyState === 1) {
    try { ws.send(JSON.stringify(obj)); return true; } catch (e) { /* 落到返回 false */ }
  }
  return false;
}

function scheduleReconnect() {
  if (wsTimer) return;
  var delay = Math.min(20000, 1500 + wsRetry * 2000);
  wsRetry++;
  wsTimer = setTimeout(function () { wsTimer = null; connectBridge(); }, delay);
}

function connectBridge(base) {
  if (base) bridgeBase = base;
  var url = toWsUrl(bridgeBase);

  // 已连到同一地址且状态正常，无需重连
  if (ws && wsUrl === url && (ws.readyState === 0 || ws.readyState === 1)) return;

  if (ws) {
    try { ws.onclose = null; ws.close(); } catch (e) { /* 忽略 */ }
    ws = null;
  }
  wsUrl = url;

  try {
    ws = new WebSocket(url);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = function () {
    wsRetry = 0;
    wsSend({ type: "hello", role: "extension", browserId: browserId,
      version: chrome.runtime.getManifest().version });
    setBadge("●", "#10b981");
    notifyTabs({ type: "bridge-state", state: bridgeState() });
  };

  ws.onmessage = function (ev) {
    var msg = null;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    handleBridgeMessage(msg);
  };

  ws.onclose = function () {
    ws = null;
    setBadge("", null);
    notifyTabs({ type: "bridge-state", state: bridgeState() });
    scheduleReconnect();
  };

  ws.onerror = function () { /* onclose 紧随其后，统一在那里重连 */ };
}

async function handleBridgeMessage(msg) {
  if (!msg || !msg.type) return;

  if (msg.type === "browser-command") {
    if (!msg.target || msg.target.browserId !== browserId) return;
    var result;
    try { result = await runBrowserCommand(msg); }
    catch (e) { result = { ok: false, error: "目标页面已关闭或刷新，请重新抓取元素" }; }
    wsSend({ type: "browser-result", requestId: msg.requestId, result: result });
    return;
  }

  if (msg.type === "start-pick") {
    var tab = await activeTab();
    var why = !tab || !tab.id ? "没找到当前标签页" : injectBlockedReason(tab.url);
    if (why || !isInjectable(tab.url)) {
      wsSend({ type: "status", payload: { kind: "start-pick", ok: false, error: why || "当前标签页不支持脚本注入" } });
      flashBadge("✕");
      return;
    }
    try {
      var r = await startPickSession(tab, msg.hint);
      wsSend({ type: "status", payload: Object.assign({ kind: "start-pick" }, r) });
    } catch (e) {
      await stopPickSession();
      wsSend({ type: "status", payload: { kind: "start-pick", ok: false, error: friendlyInjectError(e.message) } });
    }
    return;
  }

  if (msg.type === "stop-pick") {
    await stopPickSession();
    return;
  }

  if (msg.type === "ping") {
    wsSend({ type: "pong" });
    return;
  }
}

async function runBrowserCommand(msg) {
  var target = msg.target || {};
  if (!lastTarget || target.tabId !== lastTarget.tabId || target.frameId !== lastTarget.frameId ||
      !target.documentId || target.documentId !== lastTarget.documentId)
    return { ok: false, code: "stale_target", error: "抓取目标已变更，请重新抓取元素" };
  if (pickSession) return { ok: false, error: "请先确认或取消当前抓取，再校验 XPath" };
  // 只投递到原始文档；刷新、导航后不注入新页面，也不回退到当前标签页。
  return await chrome.tabs.sendMessage(target.tabId,
    { type: msg.action === "validate" || msg.action === "clear" ? "browser-validate" : "wbot-command",
      action: msg.action, xpath: msg.xpath, options: msg.options || {} },
    { documentId: target.documentId });
}

async function clearPreviousHighlight() {
  if (!lastTarget || !lastTarget.documentId) return;
  try {
    await chrome.tabs.sendMessage(lastTarget.tabId, { type: "browser-validate", action: "clear" },
      { documentId: lastTarget.documentId });
  } catch (e) { /* 原页面可能已关闭 */ }
}

/* 把消息推给所有标签页的内容脚本（用于同步桥接状态） */
function notifyTabs(msg) {
  chrome.tabs.query({}, function (tabs) {
    (tabs || []).forEach(function (t) {
      if (!t || !t.id) return;
      try {
        chrome.tabs.sendMessage(t.id, msg, function () { void chrome.runtime.lastError; });
      } catch (e) { /* 忽略 */ }
    });
  });
}

/* ---------------- 桌面版 HTTP 接口 ---------------- */
async function testBridge(base) {
  try {
    var r = await fetch(joinUrl(base, "/api/health"), { method: "GET", cache: "no-store" });
    if (!r.ok) return { ok: false, error: "桌面版返回 HTTP " + r.status };
    var j = await r.json();
    var ext = j && j.bridge ? j.bridge.extensions : null;
    return { ok: true, version: "v" + (j.version || "?"), extensions: ext };
  } catch (e) {
    return { ok: false, error: "无法连接 " + joinUrl(base, "/api/health") + "，请确认桌面版已启动" };
  }
}

async function aiGenerate(msg) {
  try {
    var r = await fetch(joinUrl(msg.bridge, "/api/ai"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html: msg.html, instruction: msg.instruction })
    });
    if (!r.ok) return { ok: false, error: "桌面版返回 HTTP " + r.status };
    return await r.json();
  } catch (e) {
    return {
      ok: false,
      error: "无法连接本地桌面版 XPath Studio（" + joinUrl(msg.bridge, "/api/ai") + "）。" +
        "请先启动桌面版，并确认其中已配置 AI 接口。"
    };
  }
}

/* 扩展 -> 桌面版：把抓取结果回传（WS 优先，失败走 HTTP 兜底） */
async function reportPicked(msg) {
  var payload = msg.payload || {};
  var viaWs = wsSend({ type: "picked", payload: payload });
  if (viaWs) return { ok: true, via: "ws" };

  // WS 不可用时的兜底：直接 POST 到桌面版
  try {
    var response = await fetch(joinUrl(pickSession ? bridgeBase : msg.bridge, "/api/bridge/result"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payload: payload })
    });
    var result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "桌面版未接受抓取结果");
    return { ok: true, via: "http" };
  } catch (e) { return { ok: false, error: "回传失败：" + e.message }; }
}

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (!msg || !msg.type) return;

  if (msg.type === "bridge-test") {
    testBridge(msg.bridge).then(sendResponse);
    return true;
  }
  if (msg.type === "ai-generate") {
    aiGenerate(msg).then(sendResponse);
    return true;
  }
  if (msg.type === "pick-lock" || msg.type === "pick-resume") {
    (msg.type === "pick-lock" ? lockPickFrame(msg, sender) : resumePickFrames(msg, sender))
      .then(sendResponse).catch(function (e) { sendResponse({ ok: false, error: e.message }); });
    return true;
  }
  if (msg.type === "picked") {
    (async function () {
      var session = pickSession;
      if (msg.sessionId && (!isPickSender(msg, sender) || session.ownerFrame !== sender.frameId))
        return { ok: false, error: "抓取会话已失效，请重新抓取" };
      var payload = msg.payload || {};
      // frameId 来自浏览器可信 sender，不接受内容脚本伪造。
      payload.frame = { tabId: sender.tab && sender.tab.id, frameId: sender.frameId || 0,
        parentFrameId: session ? ((session.frames.find(function (f) { return f.frameId === sender.frameId; }) || {}).parentFrameId) : null,
        documentId: sender.documentId || "", url: sender.url || payload.url,
        topUrl: (session && session.topUrl) || (sender.tab && sender.tab.url) || payload.url,
        isTop: !sender.frameId, xpathScope: sender.frameId ? "frame" : "page" };
      payload.browserId = browserId;
      var result = await reportPicked(Object.assign({}, msg, { payload: payload }));
      if (result.ok) {
        await clearPreviousHighlight();
        lastTarget = payload.frame;
        if (session && pickSession === session) await stopPickSession();
      }
      return result;
    })().then(sendResponse).catch(function (e) { sendResponse({ ok: false, error: e.message }); });
    return true;
  }
  if (msg.type === "picked-status") {
    if (msg.sessionId && !isPickSender(msg, sender)) { sendResponse({ ok: false }); return true; }
    if (msg.payload && msg.payload.kind === "cancel") stopPickSession();
    wsSend({ type: "status", payload: msg.payload });
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "bridge-status") {
    sendResponse(bridgeState());
    return true;
  }
  if (msg.type === "bridge-connect") {
    if (msg.bridge) bridgeBase = msg.bridge;
    connectBridge(msg.bridge);
    sendResponse({ ok: true, state: bridgeState() });
    return true;
  }
  return false;
});

/* ---------------- 启动 / 保活 ---------------- */
// Service Worker 每次被唤醒都会执行到这里，顺带确保长连接在线
connectBridge();

chrome.runtime.onStartup.addListener(function () { connectBridge(); });

// 浏览器可能休眠 SW，导致 WS 断开且定时器失效；用 alarm 兜底定期重连
chrome.alarms.create("xps-bridge-keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(function (a) {
  if (a && a.name === "xps-bridge-keepalive") connectBridge();
});

/* 安装时给出提示 */
chrome.runtime.onInstalled.addListener(function (details) {
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("welcome.html") });
  }
});
