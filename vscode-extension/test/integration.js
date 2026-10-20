'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const net = require('node:net');
const vscode = require('vscode');
const core = require('../src/core');
const FlowModel = require('../media/flow-model');
async function until(predicate) {
  const end = Date.now()+15000;
  while (Date.now()<end) { if (predicate()) return; await new Promise(resolve=>setTimeout(resolve,30)); }
  throw new Error('等待扩展操作完成超时');
}

async function verifyFlowEditor(api,workspace,check) {
  const file = path.join(workspace,'测试流程.wbot.json');
  const flow = FlowModel.sample(); flow.steps[1].params.seconds = 0;
  await fs.writeFile(file,JSON.stringify(flow,null,2));
  const doc = await vscode.workspace.openTextDocument(file);
  const messages = []; let receive, dispose;
  const panel = {webview:{
    cspSource:'vscode-webview:',asWebviewUri:uri=>uri,
    postMessage:value=>{messages.push(value);return Promise.resolve(true);},
    onDidReceiveMessage:callback=>{receive=callback;return{dispose(){}};}
  },onDidDispose:callback=>{dispose=callback;}};
  await api.flows.resolveCustomTextEditor(doc,panel);
  const session = [...api.flows.sessions].find(item=>item.panel===panel);
  try {
    receive({type:'ready'}); await until(()=>messages.some(m=>m.type==='document'));
    assert.ok(panel.webview.html.includes('Content-Security-Policy'));
    assert.ok(!panel.webview.html.includes('__NONCE__'));
    await vscode.commands.executeCommand('vscode.openWith',doc.uri,'wbot.flowEditor');
    await until(()=>vscode.window.tabGroups.all.some(g=>g.tabs.some(t=>t.input?.viewType==='wbot.flowEditor')));
    check('真实注册并打开 .wbot.json 自定义编辑器');
    const edited = structuredClone(flow); edited.name = '编辑后的流程';
    const originalVersion = doc.version;
    receive({type:'edit',flow:edited,version:originalVersion});
    await until(()=>JSON.parse(doc.getText()).name===edited.name);
    assert.equal(doc.isDirty,true);
    receive({type:'save'}); await until(()=>!doc.isDirty);
    assert.equal(JSON.parse(await fs.readFile(file,'utf8')).name,edited.name);
    receive({type:'edit',flow,version:originalVersion});
    await until(()=>messages.some(m=>m.type==='error' && m.error.includes('更新')));
    assert.equal(JSON.parse(doc.getText()).name,edited.name);
    check('Webview 消息编辑、保存及旧版本覆盖保护');
    await vscode.commands.executeCommand('undo');
    await until(()=>JSON.parse(doc.getText()).name===flow.name);
    await vscode.commands.executeCommand('redo');
    await until(()=>JSON.parse(doc.getText()).name===edited.name);
    check('自定义编辑器撤销与重做');
    receive({type:'run'}); await until(()=>messages.some(m=>m.type==='event' && m.event==='finished'));
    await until(()=>!session.child && !session.starting);
    assert.ok(messages.some(m=>m.event==='log' && m.text==='你好，WBot！'));
    check('从编辑器真实执行流程并返回逐步状态、日志和变量');
    messages.length = 0;
    const long = structuredClone(edited); long.steps = [FlowModel.step('wait')]; long.steps[0].params.seconds = 3600;
    receive({type:'edit',flow:long,version:doc.version}); await until(()=>JSON.parse(doc.getText()).steps.length===1);
    receive({type:'run'}); await until(()=>messages.some(m=>m.event==='step'));
    receive({type:'stop'}); await until(()=>messages.some(m=>m.event==='stopped'));
    await until(()=>!session.child && !session.starting);
    check('编辑器停止运行，Python 子进程退出');
    messages.length = 0;
    const debugging = structuredClone(edited);
    const first = FlowModel.step('set'); first.params = {output:'message',value:'单步后的值'};
    const disabled = FlowModel.step('log'); disabled.enabled = false; disabled.breakpoint = true;
    const second = FlowModel.step('set'); second.params = {output:'message',value:'断点后的值'}; second.breakpoint = true;
    const last = FlowModel.step('log');
    debugging.steps = [first,disabled,second,last];
    receive({type:'edit',flow:debugging,version:doc.version});
    await until(()=>JSON.parse(doc.getText()).steps.length===4);
    receive({type:'debug'});
    await until(()=>messages.some(m=>m.event==='paused' && m.reason==='entry'));
    const entry = messages.find(m=>m.event==='paused');
    assert.equal(entry.id,first.id);
    assert.equal(messages.some(m=>m.event==='step'),false);
    assert.equal(JSON.parse(await fs.readFile(file,'utf8')).steps[2].breakpoint,true);
    check('调试入口在首条指令前暂停，断点持久保存');
    const replayStart = messages.length;
    receive({type:'ready'});
    await until(()=>messages.slice(replayStart).some(m=>m.event==='paused'));
    assert.ok(messages.slice(replayStart).some(m=>m.type==='runState' && m.running && m.debugging));
    assert.ok(messages.slice(replayStart).some(m=>m.event==='variables'));
    receive({type:'step',pauseId:entry.pauseId});
    await until(()=>messages.some(m=>m.event==='paused' && m.pauseId!==entry.pauseId));
    const next = messages.find(m=>m.event==='paused' && m.pauseId!==entry.pauseId);
    assert.equal(next.id,second.id);
    assert.ok(messages.some(m=>m.event==='variables' && m.values.message==='单步后的值'));
    assert.equal(messages.some(m=>m.event==='step' && m.id===disabled.id),false);
    assert.equal(messages.filter(m=>m.event==='step' && m.state==='done').length,1);
    const staleStart = messages.length;
    receive({type:'step',pauseId:entry.pauseId});
    await until(()=>messages.slice(staleStart).some(m=>m.event==='paused'));
    assert.equal(messages.filter(m=>m.event==='step' && m.state==='done').length,1);
    check('单步恰好执行一条并跳过禁用步骤，变量更新，旧暂停命令不推进执行');
    receive({type:'resume',pauseId:next.pauseId});
    await until(()=>messages.some(m=>m.event==='finished'));
    await until(()=>!session.child && !session.starting);
    assert.ok(messages.some(m=>m.event==='log' && m.text==='断点后的值'));
    assert.equal(messages.filter(m=>m.event==='step' && m.state==='done').length,3);
    messages.length = 0;
    receive({type:'debug'});
    await until(()=>messages.some(m=>m.event==='paused'));
    const again = messages.find(m=>m.event==='paused');
    receive({type:'resume',pauseId:again.pauseId});
    await until(()=>messages.some(m=>m.event==='paused' && m.reason==='breakpoint'));
    assert.equal(messages.find(m=>m.event==='paused' && m.reason==='breakpoint').id,second.id);
    receive({type:'stop'});
    await until(()=>messages.some(m=>m.event==='stopped'));
    await until(()=>!session.child && !session.starting);
    assert.equal(messages.some(m=>m.event==='step' && m.id===second.id),false);
    check('继续运行命中断点；断点暂停时停止不执行当前指令');
  } finally { dispose(); }
}

async function executeTask(command) {
  let listener;
  const completed = new Promise((resolve,reject) => {
    const timer = setTimeout(() => { listener.dispose(); reject(new Error(command+' 任务未完成')); },30000);
    listener = vscode.tasks.onDidEndTaskProcess(event => { if (event.execution.task.source === 'WBot') { clearTimeout(timer); listener.dispose(); resolve(event.exitCode); } });
  });
  await vscode.commands.executeCommand(command);
  assert.equal(await completed,0,command);
}

async function run() {
  const workspace = vscode.workspace.workspaceFolders[0].uri.fsPath;
  const report = {checks:[],passed:false};
  const check = name => report.checks.push(name);
  let api;
  try {
    assert.equal(vscode.workspace.isTrusted,true);
    const extension = vscode.extensions.getExtension('xpath-studio-local.wbot-studio');
    assert.ok(extension);
    api = await extension.activate();
    check('扩展激活');
    const commands = await vscode.commands.getCommands(true);
    for (const command of extension.packageJSON.contributes.commands) assert.ok(commands.includes(command.command),command.command);
    check('全部 '+extension.packageJSON.contributes.commands.length+' 个命令已注册');
    const socket = net.createServer();
    await new Promise(resolve => socket.listen(0,'127.0.0.1',resolve));
    const port = socket.address().port;
    await new Promise(resolve => socket.close(resolve));
    const base = `http://127.0.0.1:${port}`, database = path.join(workspace,'elements.sqlite3');
    const cfg = vscode.workspace.getConfiguration('wbot');
    await cfg.update('bridgeUrl',base,vscode.ConfigurationTarget.Global);
    await cfg.update('pythonPath',process.env.WBOT_TEST_PYTHON,vscode.ConfigurationTarget.Global);
    await cfg.update('libraryPath',database,vscode.ConfigurationTarget.Global);
    await executeTask('wbot.installRuntime');
    check('安装内置 wheel 到测试 Python 环境');
    await vscode.commands.executeCommand('wbot.startBridge');
    assert.ok(api.bridge.child);
    assert.equal((await core.request(base,'/api/health')).wbot,'0.1.0');
    check('从 VS Code 启动真实 Python 桥接服务');
    const record = (await core.request(base,'/api/elements/save',{record:{name:'搜索"框 ${1}',group:'中文分组',xpath:'//input[@id="q"]',url:'https://example.com'}})).item;
    await api.refresh();
    assert.equal(api.getElements().length,1);
    const groups = api.provider.getChildren();
    assert.equal(groups[0].name,'中文分组');
    const nodes = api.provider.getChildren(groups[0]);
    assert.equal(api.provider.getTreeItem(nodes[0]).label,record.name);
    check('元素库读取、分组及 TreeItem');
    const doc = await vscode.workspace.openTextDocument({language:'python',content:''});
    await vscode.window.showTextDocument(doc);
    await vscode.commands.executeCommand('wbot.insertElement',nodes[0]);
    assert.equal(doc.getText().replace(/\r\n/g,'\n'),core.elementCode(record,{baseUrl:base,libraryPath:database}));
    check('Python 编辑器插入正确转义的元素调用代码');
    // 真实运行任务：验证解释器、参数、工作目录和库环境，仅读写隔离工作区。
    const script = path.join(workspace,'task_test.py');
    const output = path.join(workspace,'task-result.json');
    await fs.writeFile(script,'import json, os, sys\nfrom wbot import ElementLibrary\nfrom pathlib import Path\n' +
      `Path(${core.pyString(output)}).write_text(json.dumps({"args":sys.argv[1:],"cwd":os.getcwd(),"bridge":os.environ.get("WBOT_BRIDGE_URL"),"count":len(ElementLibrary().list())}), encoding="utf-8")\n`);
    const args = ['中文 参数','$(not-shell)','a"b'];
    await cfg.update('scriptArgs',args,vscode.ConfigurationTarget.Global);
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(script));
    await executeTask('wbot.runFile');
    const result = JSON.parse(await fs.readFile(output,'utf8'));
    assert.deepEqual(result.args,args);
    assert.equal(result.cwd.toLowerCase(),workspace.toLowerCase());
    assert.equal(result.bridge,base);
    assert.equal(result.count,1);
    check('真实 VS Code ProcessExecution 运行 Python，参数、目录、元素库与环境正确');
    await verifyFlowEditor(api,workspace,check);
    await vscode.commands.executeCommand('wbot.stopBridge');
    assert.equal(api.bridge.child,null);
    await assert.rejects(core.request(base,'/api/health'));
    check('停止本扩展创建的服务');
    report.passed = true;
  } catch (error) { report.error = error.stack; throw error; }
  finally {
    if (api) await api.bridge.stop();
    await fs.writeFile(path.join(workspace,'integration-report.json'),JSON.stringify(report,null,2));
  }
}
module.exports = {run};
