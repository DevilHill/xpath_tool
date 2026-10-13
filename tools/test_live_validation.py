"""真实 Chrome：抓取跨域 iframe -> 桌面校验 -> 原页面同步高亮。"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import extension_installer as ei
from app.ws_bridge import WSClientConn, HUB


class PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ('<button id="inside" style="margin:40px;padding:24px">Live button</button>'
                if self.path == '/frame' else
                f'<button id="inside">Top button</button><iframe width="650" height="400" '
                f'src="http://localhost:{self.server.server_port}/frame"></iframe>')
        raw = ('<!DOCTYPE html><html><head><title>Live test</title></head><body>' + body + '</body></html>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


def main():
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    work = Path(tempfile.mkdtemp(prefix='live-validation-', dir=ROOT / 'build'))
    from app import server
    server.CONFIG_PATH = work / 'config.json'
    app, port = server.run_server(0)
    page = ThreadingHTTPServer(('127.0.0.1', 0), PageHandler)
    threading.Thread(target=page.serve_forever, daemon=True).start()
    ext = work / 'extension'
    shutil.copytree(ROOT / 'extension', ext)
    bg = ext / 'background.js'
    bg.write_text(bg.read_text(encoding='utf-8').replace('http://127.0.0.1:8790',
                  f'http://127.0.0.1:{port}'), encoding='utf-8')
    debug_port = ei._free_port()
    chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
    chrome_log = (work / 'chrome.log').open('wb')
    proc = subprocess.Popen([chrome, '--headless=new', '--no-proxy-server', '--no-first-run',
        '--no-default-browser-check', '--enable-unsafe-extension-debugging',
        f'--remote-debugging-port={debug_port}', f'--user-data-dir={work / "profile"}',
        '--window-size=1440,900', 'about:blank'], stdout=subprocess.DEVNULL, stderr=chrome_log)
    conn = None
    serial, checks = 0, 0

    def call(method, params=None, sid=None):
        nonlocal serial
        serial += 1
        result = conn.call(method, params or {}, serial, timeout=25, session_id=sid)
        assert result and not result.get('error'), result
        return result.get('result', {})

    def evaluate(sid, code):
        result = call('Runtime.evaluate', {'expression': code, 'awaitPromise': True, 'returnByValue': True}, sid)
        assert not result.get('exceptionDetails'), result
        return result.get('result', {}).get('value')

    def check(name, value):
        nonlocal checks
        assert value, name
        checks += 1
        print(f'[OK] {name}', flush=True)

    def wait_document(sid):
        return evaluate(sid, "new Promise(r=>{let n=0;const t=setInterval(()=>{if(document.readyState==='complete'||++n>100){clearInterval(t);r(document.readyState==='complete');}},50);})")

    try:
        debugger = ei._wait_debugger(debug_port)
        assert debugger, f"Chrome 未就绪：exit={proc.poll()} log={work / 'chrome.log'}"
        conn = WSClientConn(debugger, timeout=25)
        conn.connect()
        eid = call('Extensions.loadUnpacked', {'path': str(ext)})['id']
        target = call('Target.createTarget', {'url': f'http://127.0.0.1:{page.server_port}/'})['targetId']
        page_sid = call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
        assert wait_document(page_sid)
        sw = None
        for _ in range(100):
            sw = next((t for t in call('Target.getTargets')['targetInfos'] if t['type'] == 'service_worker' and eid in t['url']), None)
            if sw and HUB.stats()['extensions']: break
            time.sleep(.05)
        assert sw and HUB.stats()['extensions']
        sid = call('Target.attachToTarget', {'targetId': sw['targetId'], 'flatten': True})['sessionId']
        check('扩展通过真实 WebSocket 连接桌面服务', HUB.stats()['extensions'] == 1)
        setup = evaluate(sid, """(async()=>{
          globalThis.testTab=(await chrome.tabs.query({})).find(t=>(t.url||'').startsWith('http://127.0.0.1:') && (t.url||'').includes('PORT'));
          globalThis.child=(await chrome.webNavigation.getAllFrames({tabId:testTab.id})).find(f=>f.frameId!==0);
          globalThis.runFrame=async(fn)=>(await chrome.scripting.executeScript({target:{tabId:testTab.id,frameIds:[child.frameId]},func:fn}))[0].result;
          return await startPickSession(testTab);
        })()""".replace('PORT', str(page.server_port)))
        check('真实跨域框架进入抓取', setup['frameCount'] == 2)
        evaluate(sid, """runFrame(()=>{const b=document.querySelector('#inside'),r=b.getBoundingClientRect();
          b.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:r.x+10,clientY:r.y+10}));
          b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,ctrlKey:true,clientX:r.x+10,clientY:r.y+10}));})""")
        check('框架锁定确认卡出现', evaluate(sid, "runFrame(()=>new Promise(r=>{let n=0;const t=setInterval(()=>{const card=document.querySelector('#__xpath_studio_overlay__').shadowRoot.querySelector('.ov-review');if(card||++n>100){clearInterval(t);r(!!card);}},50);} ))"))
        check('确认回传成功', evaluate(sid, """(async()=>{await runFrame(()=>document.querySelector('#__xpath_studio_overlay__').shadowRoot.querySelector('[data-action="confirm"]').click());
          for(let i=0;i<100&&pickSession;i++) await new Promise(r=>setTimeout(r,50));return !pickSession&&!!lastTarget;})()"""))
        check('抓取来源带浏览器与文档身份', HUB.last_pick and HUB.last_pick['browserId'] and HUB.last_pick['frame']['documentId'])
        ui_target = call('Target.createTarget', {'url': f'http://127.0.0.1:{port}/'})['targetId']
        ui = call('Target.attachToTarget', {'targetId': ui_target, 'flatten': True})['sessionId']
        assert wait_document(ui)
        check('桌面刷新恢复抓取来源且移除旧面板', evaluate(ui, "new Promise(r=>{let n=0;const t=setInterval(()=>{if(document.querySelector('#xpathInput').value||++n>100){clearInterval(t);r(!document.querySelector('#domTree')&&!document.querySelector('#htmlInput')&&!!document.querySelector('#xpathInput').value);}},50);})"))

        def validate(xpath):
            return evaluate(ui, """(async()=>{document.querySelector('#xpathInput').value=XP;
              document.querySelector('#btnValidate').click();for(let i=0;i<200;i++){
                await new Promise(r=>setTimeout(r,50));const m=document.querySelector('#validateMsg');
                if(!m.classList.contains('loading'))return {msg:m.textContent,count:document.querySelector('#matchCount').textContent};
              }return null;})()""".replace('XP', json.dumps(xpath)))

        def overlay_count():
            return evaluate(sid, "runFrame(()=>document.querySelector('#__xpath_studio_overlay__').shadowRoot.querySelectorAll('.ov-hl').length)")

        result = validate("//button[@id='inside']")
        check('点击桌面校验得到真实结果', result and result['count'] == '1' and '同步高亮' in result['msg'])
        check('来源 iframe 中出现真实可见高亮框', overlay_count() == 1)
        check('顶层同 ID 元素未被误高亮', evaluate(sid, "(async()=> (await chrome.scripting.executeScript({target:{tabId:testTab.id,frameIds:[0]},func:()=>!document.querySelector('#__xpath_studio_overlay__').shadowRoot.querySelector('.ov-hl')}))[0].result)()"))
        evaluate(sid, "runFrame(()=>document.body.appendChild(document.querySelector('#inside').cloneNode(true)))")
        result = validate("//button[@id='inside']")
        check('DOM 变化后按实时页面匹配两个节点', result['count'] == '2' and overlay_count() == 2)
        result = validate('//missing')
        check('零匹配清除此前高亮', result['count'] == '0' and overlay_count() == 0)
        validate("//button[@id='inside']")
        result = validate('//*[')
        check('无效 XPath 清除高亮且报错', '表达式无效' in result['msg'] and overlay_count() == 0)
        result = validate('count(//button)')
        check('标量结果不误报高亮', '无元素可高亮' in result['msg'] and overlay_count() == 0)
        validate('//button')
        evaluate(ui, "document.querySelector('#btnClear').click()")
        check('清空同步移除浏览器高亮', evaluate(sid, "runFrame(()=>new Promise(r=>{let n=0;const t=setInterval(()=>{const c=document.querySelector('#__xpath_studio_overlay__').shadowRoot.querySelectorAll('.ov-hl').length;if(c===0||++n>100){clearInterval(t);r(c===0);}},50);}))"))
        validate('//button')
        shot = call('Page.captureScreenshot', {'format': 'png'}, ui)['data']
        out = ROOT / 'output/playwright'
        out.mkdir(parents=True, exist_ok=True)
        (out / 'workbench-live.png').write_bytes(base64.b64decode(shot))
        evaluate(sid, 'chrome.tabs.reload(testTab.id)')
        time.sleep(.5)
        result = validate('//button')
        check('页面刷新后不高亮新文档并要求重新抓取', '重新抓取' in result['msg'])
        print(f'实时联动：{checks} 项通过', flush=True)
        return 0
    finally:
        if conn:
            try: call('Browser.close')
            except Exception: pass
            conn.close()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
        app.shutdown(); app.server_close()
        page.shutdown(); page.server_close()
        chrome_log.close()


if __name__ == '__main__':
    raise SystemExit(main())
