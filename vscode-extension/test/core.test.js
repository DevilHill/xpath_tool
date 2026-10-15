'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const os = require('node:os');
const {spawnSync} = require('node:child_process');
const core = require('../src/core');

test('服务地址限制与元素库路径', () => {
  assert.equal(core.bridgeUrl('http://127.0.0.1:8790/'), 'http://127.0.0.1:8790');
  for (const url of ['https://127.0.0.1:8790', 'http://example.com', 'http://localhost', 'http://127.0.0.1/path', 'http://user@127.0.0.1', 'http://127.0.0.1/?a=b']) assert.throws(() => core.bridgeUrl(url));
  assert.throws(() => core.libraryPath('relative.sqlite3'));
  assert.equal(core.libraryPath('~/test.sqlite3'), path.join(os.homedir(), 'test.sqlite3'));
});

test('代码生成正确转义名称并可由 Python 解析', () => {
  const name = '中文"\\\n${1:占位}\u2028';
  const code = core.elementCode({name,group:"分组'"}, {baseUrl:'http://127.0.0.1:8790',libraryPath:path.resolve('test.sqlite3')});
  assert.ok(code.includes(core.pyString(name)));
  assert.ok(code.includes('group='));
  const python = process.env.WBOT_TEST_PYTHON || 'python';
  const result = spawnSync(python, ['-I','-c','import ast,sys; ast.parse(sys.stdin.buffer.read().decode("utf-8"))'], {input:code, encoding:'utf8',windowsHide:true});
  assert.equal(result.status, 0, result.stderr || String(result.error));
});

test('抓取结果与框架匹配检查', () => {
  assert.throws(() => core.pickedRecord(null));
  const payload = {xpath:'//input',text:'输入框',url:'https://top.example',frame:{url:'https://frame.example',frameId:2,isTop:false,topUrl:'https://top.example'}};
  const record = core.pickedRecord(payload);
  assert.equal(record.url,'https://frame.example');
  assert.equal(core.scopeMatches(record,payload),true);
  assert.equal(core.scopeMatches(record,{...payload,frame:{...payload.frame,frameId:3}}),false);
  assert.equal(core.scopeMatches({...record,url:'https://other.example'},payload),false);
});

test('HTTP 客户端处理 JSON、业务失败、非法响应与超时', async t => {
  const server = http.createServer((req,res) => {
    if (req.url === '/api/hang') return;
    if (req.url === '/api/bad') return res.end('__REPORT_DATA__');
    if (req.url === '/api/fail') return res.end(JSON.stringify({ok:false,error:'业务错误'}));
    if (req.url === '/api/redirect') { res.writeHead(302,{Location:'http://example.com'}); return res.end('{"ok":true}'); }
    let data = ''; req.on('data',chunk => data += chunk);
    req.on('end',() => res.end(JSON.stringify({ok:true,method:req.method,body:data ? JSON.parse(data) : null})));
  });
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  assert.deepEqual(await core.request(base,'/api/test',{value:'中文'}), {ok:true,method:'POST',body:{value:'中文'}});
  await assert.rejects(core.request(base,'/api/fail'), /业务错误/);
  await assert.rejects(core.request(base,'/api/bad'), /不是 JSON/);
  await assert.rejects(core.request(base,'/api/redirect'), /302/);
  await assert.rejects(core.request(base,'/api/hang',undefined,50), /超时/);
  await assert.rejects(core.request(base,'//example.com/api/'), /接口路径/);
});
