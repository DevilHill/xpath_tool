"""真实无头 Chrome：跨域框架拾取、确认、层级、取消与 HTTP 回传。
仅操作 build/ 下独立测试副本及 profile，不读取或写入注册表。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import extension_installer as ei
from app.ws_bridge import WSClientConn

received = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        port = self.server.server_port
        if self.path == "/frame":
            html = '<html><head><title>Frame</title></head><body><section id="holder"><button id="inside" style="margin:30px;padding:20px">Frame button</button></section></body></html>'
        else:
            html = f'<html><head><title>Cross-frame test</title></head><body><h1>Frame picking</h1><iframe src="http://localhost:{port}/frame" width="650" height="430"></iframe></body></html>'
        raw = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/api/bridge/result":
            received.append(json.loads(raw)["payload"])
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass


def main():
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    assert chrome.exists(), "本测试需要本机 Chrome"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    work = Path(tempfile.mkdtemp(prefix="frame-test-", dir=ROOT / "build"))
    ext = work / "extension"
    shutil.copytree(ROOT / "extension", ext)
    bg = ext / "background.js"
    bg.write_text(bg.read_text(encoding="utf-8").replace(
        "http://127.0.0.1:8790", f"http://127.0.0.1:{srv.server_port}"), encoding="utf-8")
    dbg = ei._free_port()
    proc = subprocess.Popen([str(chrome), "--headless=new", "--no-proxy-server",
        "--no-first-run", "--no-default-browser-check", "--enable-unsafe-extension-debugging",
        f"--remote-debugging-port={dbg}", f"--user-data-dir={work / 'profile'}",
        "--window-size=1100,800", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    conn = None
    serial = 0
    checks = 0

    def check(name, value):
        nonlocal checks
        assert value, name
        checks += 1
        print(f"[OK] {name}", flush=True)

    def call(method, params=None, sid=None):
        nonlocal serial
        serial += 1
        raw = conn.call(method, params or {}, msg_id=serial, session_id=sid, timeout=25)
        assert raw is not None, f"CDP 无响应：{method} 会话={sid} 浏览器退出码={proc.poll()}"
        assert not raw.get("error"), raw
        return raw.get("result", {})

    def evaluate(sid, expr):
        res = call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, sid)
        assert not res.get("exceptionDetails"), res
        return res.get("result", {}).get("value")

    try:
        ws = ei._wait_debugger(dbg)
        assert ws, "浏览器调试端口未就绪"
        conn = WSClientConn(ws, timeout=25)
        conn.connect()
        eid = call("Extensions.loadUnpacked", {"path": str(ext)})["id"]
        target = call("Target.createTarget", {"url": f"http://127.0.0.1:{srv.server_port}/"})["targetId"]
        page_sid = call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        check("跨域测试页面完成加载", evaluate(page_sid, """new Promise(resolve => {
          let n=0; let timer=setInterval(() => { if(document.readyState==='complete' || ++n>100) {
          clearInterval(timer); resolve(document.readyState==='complete'); } },50);
        })"""))
        sw = None
        until = time.monotonic() + 12
        while time.monotonic() < until:
            sw = next((t for t in call("Target.getTargets")["targetInfos"]
                       if t["type"] == "service_worker" and eid in t["url"]), None)
            if sw:
                break
            time.sleep(.1)
        assert sw, "扩展后台未启动"
        sid = call("Target.attachToTarget", {"targetId": sw["targetId"], "flatten": True})["sessionId"]
        call("Runtime.enable", sid=sid)
        setup = evaluate(sid, """(async()=>{
          globalThis.testTab=(await chrome.tabs.query({})).find(t=>(t.url||'').includes('127.0.0.1') && !(t.url||'').includes('chrome-extension'));
          globalThis.testFrames=await chrome.webNavigation.getAllFrames({tabId:testTab.id});
          globalThis.child=testFrames.find(f=>f.frameId!==0);
          globalThis.runFrame=async(fn)=> (await chrome.scripting.executeScript({target:{tabId:testTab.id,frameIds:[child.frameId]},func:fn}))[0].result;
          return await startPickSession(testTab);
        })()""")
        check("顶层与跨域iframe均进入抓取", setup["frameCount"] == 2)
        picked_state = evaluate(sid, """runFrame(()=>{
          const b=document.querySelector('#inside'); const r=b.getBoundingClientRect();
          b.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:r.x+10,clientY:r.y+10}));
          document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true}));
          const root=document.querySelector('#__xpath_studio_overlay__').shadowRoot;
          const parent=root.querySelector('.ov-tip').textContent;
          document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
          b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,ctrlKey:true,clientX:r.x+10,clientY:r.y+10}));
          return parent;
        })""")
        check("真实DOM父元素切换", "holder" in picked_state)
        review = evaluate(sid, """runFrame(()=>new Promise(resolve=>{
          let n=0; const timer=setInterval(()=>{const root=document.querySelector('#__xpath_studio_overlay__').shadowRoot;
          const card=root.querySelector('.ov-review'); if(card || ++n>60){clearInterval(timer);
          resolve(card ? {text:card.textContent,width:card.getBoundingClientRect().width, height:card.getBoundingClientRect().height}:null);}},50);
        }))""")
        check("真实iframe内显示锁定确认卡", review and "iframe" in review["text"])
        check("确认卡可见且未挤成竖排", review["width"] > 250 and review["height"] > 60)
        check("确认前未回传", not received)
        await_result = evaluate(sid, """(async()=>{
          await runFrame(()=>document.querySelector('#__xpath_studio_overlay__').shadowRoot.querySelector('[data-action="confirm"]').click());
          for(let i=0;i<100;i++){ if(!pickSession) return true; await new Promise(r=>setTimeout(r,50)); }
          return false;
        })()""")
        check("确认后结束整次会话", await_result)
        check("收到真实HTTP回传且只一次", len(received) == 1)
        payload = received[0]
        check("抓到框架内部按钮而非iframe标签", payload["id"] == "inside" and payload["tag"] == "button")
        check("XPath在框架内唯一", payload["xpath"] == "//button[@id='inside']" and payload["matchCount"] == 1)
        check("来源信息区分顶层与跨域框架", payload["frame"]["frameId"] > 0 and
              "localhost" in payload["frame"]["url"] and "127.0.0.1" in payload["frame"]["topUrl"])
        check("回传包含实时文档身份且不含整页快照", bool(payload["frame"]["documentId"]) and
              bool(payload["browserId"]) and "pageHtml" not in payload)
        cancel = evaluate(sid, """(async()=>{
          await startPickSession(testTab);
          await runFrame(()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})));
          for(let i=0;i<60 && pickSession;i++) await new Promise(r=>setTimeout(r,50));
          const states=await Promise.all(testFrames.map(f=>chrome.tabs.sendMessage(testTab.id,{type:'ping'},{frameId:f.frameId})));
          return !pickSession && states.every(s=>!s.picking);
        })()""")
        check("iframe内Esc取消清理所有框架", cancel)
        check("取消不新增回传", len(received) == 1)
        race = evaluate(sid, """(async()=>{
          const starting = startPickSession(testTab);
          await stopPickSession();
          await starting;
          return pickSession === null;
        })()""")
        check("启动期间立即取消不会留下会话", race)
        wrong_tab = evaluate(sid, """(async()=>{
          await startPickSession(testTab);
          const other=await chrome.tabs.create({url:'about:blank',active:true});
          await handleBridgeMessage({type:'stop-pick'});
          const states=await Promise.all(testFrames.map(f=>chrome.tabs.sendMessage(testTab.id,{type:'ping'},{frameId:f.frameId})));
          await chrome.tabs.remove(other.id);
          return states.every(s=>!s.picking);
        })()""")
        check("切到其它标签后取消仍清理原标签", wrong_tab)
        print(f"真实框架回归：{checks} 项通过", flush=True)
        return 0
    finally:
        if conn:
            try:
                call("Browser.close")
            except Exception:
                pass
            conn.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        srv.shutdown()
        srv.server_close()
        # 测试 profile 保留在项目 build/，不处理个人目录。


if __name__ == "__main__":
    raise SystemExit(main())
