/* WebSocket 客户端探针（Node 22 内置 WebSocket）
 *
 * 用法：node tools/ws_client_probe.js ws://127.0.0.1:PORT/ws
 *
 * 行为：
 *   1. 连上后发送 {"type":"hello","role":"extension"}
 *   2. 向 stdout 打印 {"event":"ready"}，等待父进程触发抓取
 *   3. 收到 {"type":"start-pick"} 后回传 {"type":"picked", ...}
 *   4. 打印 {"event":"done"} 并退出
 */
"use strict";

const url = process.argv[2];
if (!url) {
  console.log(JSON.stringify({ event: "error", message: "缺少 ws url 参数" }));
  process.exit(1);
}

const seen = [];
let stage = 0;

const timer = setTimeout(() => {
  console.log(JSON.stringify({ event: "error", message: "超时未收到 start-pick", seen }));
  process.exit(1);
}, 20000);

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

const ws = new WebSocket(url);

ws.onopen = function () {
  ws.send(JSON.stringify({ type: "hello", role: "extension", version: "probe" }));
};

ws.onmessage = function (ev) {
  let msg = null;
  try { msg = JSON.parse(ev.data); } catch (e) { return; }
  seen.push(msg);

  if (msg.type === "hello" && stage === 0) {
    stage = 1;
    emit({ event: "ready", server: msg.server, version: msg.version });
    return;
  }

  if (msg.type === "start-pick" && stage === 1) {
    stage = 2;
    ws.send(JSON.stringify({
      type: "picked",
      payload: {
        tag: "button",
        id: "login-btn",
        xpath: "//button[@id='login-btn']",
        url: "https://shop.example.com/login",
        title: "示例站点",
        score: 88
      }
    }));
    setTimeout(function () {
      clearTimeout(timer);
      emit({ event: "done", seen: seen.map(function (m) { return m.type; }) });
      ws.close();
      process.exit(0);
    }, 400);
    return;
  }
};

ws.onerror = function (e) {
  clearTimeout(timer);
  emit({ event: "error", message: String((e && e.message) || e) });
  process.exit(1);
};
