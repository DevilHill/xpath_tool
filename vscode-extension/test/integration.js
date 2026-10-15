'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const net = require('node:net');
const vscode = require('vscode');
const core = require('../src/core');

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
    check('全部 23 个命令已注册');
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
