'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const M = require('../media/flow-model');

async function run(flow, {stop = false} = {}) {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(),'wbot-flow-'));
  const child = spawn(process.env.WBOT_TEST_PYTHON || 'python',['-I','-X','utf8','-u',path.resolve(__dirname,'../scripts/flow_runner.py')],
    {cwd:workspace,stdio:['pipe','pipe','pipe'],windowsHide:true});
  const events = []; let buffer = '', errors = '';
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', data => {
    buffer += data;
    let newline;
    while ((newline = buffer.indexOf('\n')) !== -1) {
      const event = JSON.parse(buffer.slice(0,newline)); buffer = buffer.slice(newline+1); events.push(event);
      if (stop && event.event === 'step' && event.state === 'running') child.stdin.write('stop\n');
    }
  });
  child.stderr.on('data', data => errors += data);
  child.stdin.on('error',()=>{});
  const finished = new Promise((resolve,reject) => {
    child.once('error',reject);
    const timer = setTimeout(()=>{ child.kill(); reject(new Error('执行超时')); },10000);
    child.once('close', code => { clearTimeout(timer); resolve(code); });
  });
  child.stdin.write(JSON.stringify(flow)+'\n');
  try { return {code:await finished,events,errors,workspace}; }
  catch (error) { await fs.rm(workspace,{recursive:true,force:true}); throw error; }
}
const withSteps = (...steps) => ({...M.sample(),steps});
const step = (type,params) => ({...M.step(type),params:{...M.step(type).params,...params}});

test('模型拒绝重复 ID、未知动作和非法参数，保留 Unicode 文本', () => {
  const flow = M.sample(); assert.equal(M.validate(flow).name,flow.name);
  assert.throws(()=>M.validate({...flow,version:2}));
  assert.throws(()=>M.validate({...flow,steps:[flow.steps[0],flow.steps[0]]}));
  assert.throws(()=>M.validate(withSteps({...M.step('log'),type:'exec'})));
  assert.throws(()=>M.validate(withSteps(step('wait',{seconds:Infinity}))));
  assert.throws(()=>M.validate(withSteps(step('set',{output:'a.b'}))));
  assert.equal(M.validate(withSteps(step('log',{text:'<script>中文 ${message}</script>'}))).steps.length,1);
});

test('真实解释执行：变量替换、日志、文件写入读取、禁用步骤', async t => {
  const skipped = step('log',{text:'不应出现'}); skipped.enabled = false;
  const flow = withSteps(step('set',{output:'name',value:'世界'}),step('replace',{text:'你好 ${name}',old:'你好',new:'Hello',output:'message'}),
    step('file.write',{path:'output/中文.txt',text:'${message}'}),step('file.read',{path:'output/中文.txt',output:'readback'}),
    step('log',{text:'${readback}'}),skipped);
  const result = await run(flow); t.after(()=>fs.rm(result.workspace,{recursive:true,force:true}));
  assert.equal(result.code,0,result.errors);
  assert.equal(result.errors,'');
  assert.equal(await fs.readFile(path.join(result.workspace,'output/中文.txt'),'utf8'),'Hello 世界');
  assert.deepEqual(result.events.filter(e=>e.event==='log').map(e=>e.text),['Hello 世界']);
  assert.equal(result.events.at(-1).event,'finished');
  assert.equal(result.events.filter(e=>e.event==='step' && e.state==='done').length,5);
});

test('失败定位与停止后续副作用', async t => {
  const failure = step('log',{text:'${missing}'});
  const result = await run(withSteps(failure,step('file.write',{path:'should-not-exist.txt',text:'bad'})));
  t.after(()=>fs.rm(result.workspace,{recursive:true,force:true}));
  assert.equal(result.code,1);
  assert.equal(result.events.at(-1).id,failure.id);
  assert.match(result.events.at(-1).error,/变量尚未定义/);
  await assert.rejects(fs.access(path.join(result.workspace,'should-not-exist.txt')));
});

test('拒绝路径越界与未经支持的执行动作', async t => {
  const result = await run(withSteps(step('file.write',{path:'../outside.txt',text:'bad'})));
  t.after(()=>fs.rm(result.workspace,{recursive:true,force:true}));
  assert.equal(result.code,1);
  assert.match(result.events.at(-1).error,/工作区/);
  const unknown = await run(withSteps({...M.step('log'),type:'python.eval'}));
  t.after(()=>fs.rm(unknown.workspace,{recursive:true,force:true}));
  assert.equal(unknown.code,1); assert.equal(unknown.events.length,1);
});

test('运行前完整校验；缺少网页连接时明确失败', async t => {
  const result = await run(withSteps(step('file.write',{path:'not-written.txt',text:'x'}),M.step('web.click')));
  t.after(()=>fs.rm(result.workspace,{recursive:true,force:true}));
  assert.equal(result.code,1);
  await assert.rejects(fs.access(path.join(result.workspace,'not-written.txt')));
  const browser = await run(withSteps(step('web.click',{xpath:'//button'})));
  t.after(()=>fs.rm(browser.workspace,{recursive:true,force:true}));
  assert.match(browser.events.at(-1).error,/连接已抓取网页/);
});

test('停止正在等待的流程，后续指令不执行', async t => {
  const begin = Date.now();
  const result = await run(withSteps(step('wait',{seconds:3600}),step('log',{text:'不应出现'})),{stop:true});
  t.after(()=>fs.rm(result.workspace,{recursive:true,force:true}));
  assert.equal(result.code,130);
  assert.ok(Date.now()-begin < 5000);
  assert.equal(result.events.at(-1).event,'stopped');
  assert.equal(result.events.some(e=>e.event==='log'),false);
});
