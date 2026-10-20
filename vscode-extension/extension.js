'use strict';
const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const core = require('./src/core');
const {BridgeManager} = require('./src/bridge');
const {FlowEditor} = require('./src/flow-editor');

let manager, flows;
function activate(context) {
  const output = vscode.window.createOutputChannel('WBot');
  const runtime = path.join(context.extensionPath, 'runtime');
  manager = new BridgeManager(runtime, text => output.append(text));
  const changes = new vscode.EventEmitter();
  let records = [], query = '', generation = 0, picking = false;
  const settings = resource => {
    const cfg = vscode.workspace.getConfiguration('wbot', resource);
    return {baseUrl:core.bridgeUrl(cfg.get('bridgeUrl')), libraryPath:core.libraryPath(cfg.get('libraryPath')),
      pythonPath:cfg.get('pythonPath'), scriptArgs:cfg.get('scriptArgs', [])};
  };
  function trusted() {
    if (!vscode.workspace.isTrusted) throw new Error('请先将工作区设为受信任，再使用 WBot');
    if (vscode.env.remoteName) throw new Error('此版本仅支持本机 VS Code 窗口，请在本机打开项目');
  }
  const api = (endpoint, body) => { trusted(); return core.request(settings().baseUrl, endpoint, body); };
  const provider = {
    onDidChangeTreeData:changes.event,
    getChildren(node) {
      const items = records.filter(r => [r.name,r.group,r.xpath,r.description].some(v => String(v || '').toLowerCase().includes(query.toLowerCase())));
      if (node) return node.kind === 'group' ? items.filter(r => r.group === node.name).map(record => ({kind:'element',record})) : [];
      return [...new Set(items.map(r => r.group))].sort().map(name => ({kind:'group',name,count:items.filter(r => r.group === name).length}));
    },
    getTreeItem(node) {
      if (node.kind === 'group') {
        const item = new vscode.TreeItem(node.name, vscode.TreeItemCollapsibleState.Expanded);
        item.description = String(node.count); item.iconPath = new vscode.ThemeIcon('folder'); return item;
      }
      const r = node.record, item = new vscode.TreeItem(r.name, vscode.TreeItemCollapsibleState.None);
      item.id = r.id; item.contextValue = 'wbot.element'; item.iconPath = new vscode.ThemeIcon('symbol-field');
      item.description = r.xpath; item.tooltip = `${r.group} / ${r.name}\n${r.xpath}\n${r.url || ''}\n${r.description || ''}`;
      item.command = {command:'wbot.copyXPath', title:'复制 XPath', arguments:[node]}; return item;
    }
  };
  const view = vscode.window.createTreeView('wbot.elements', {treeDataProvider:provider, showCollapseAll:true});
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 12);
  status.text = '$(plug) WBot'; status.tooltip = '启动 / 连接 WBot 浏览器服务'; status.command = 'wbot.startBridge'; status.show();
  async function refresh(silent = false) {
    const current = ++generation;
    try {
      const data = await api('/api/elements');
      if (!Array.isArray(data.items)) throw new Error('元素库响应无效，请更新浏览器服务');
      if (current !== generation) return;
      records = data.items; view.message = query ? `搜索：${query}` : `${records.length} 个元素`;
      status.text = '$(check) WBot'; view.description = '已连接'; changes.fire();
      return records;
    } catch (error) {
      if (current !== generation) return;
      records = []; view.message = '服务未连接；点击插头图标启动。'; view.description = '离线';
      status.text = '$(plug) WBot'; changes.fire();
      if (!silent) throw error;
    }
  }
  async function pythonExecutable(resource) {
    const configured = settings(resource).pythonPath;
    if (configured) return configured;
    const extension = vscode.extensions.getExtension('ms-python.python');
    if (extension) {
      try {
        const py = extension.isActive ? extension.exports : await extension.activate();
        const env = py.environments?.getActiveEnvironmentPath(resource);
        if (env) { const resolved = await py.environments.resolveEnvironment(env); if (resolved?.executable?.uri) return resolved.executable.uri.fsPath; }
      } catch (error) { output.appendLine('读取 Python 扩展解释器：' + error.message); }
    }
    const folder = resource && vscode.workspace.getWorkspaceFolder(resource) || vscode.workspace.workspaceFolders?.[0];
    if (folder) {
      const candidate = path.join(folder.uri.fsPath, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
      try { await fs.access(candidate); return candidate; } catch {}
    }
    return 'python';
  }
  async function chooseElement(node) {
    // 菜单参数仅作为ID引用，始终从当前加载数据选择，不接受任意调用对象。
    const found = records.find(r => r.id === node?.record?.id);
    if (found) return found;
    if (!records.length) await refresh();
    return (await vscode.window.showQuickPick(records.map(record => ({label:record.name,description:record.group,detail:record.xpath,record})),
      {placeHolder:'选择元素',matchOnDescription:true,matchOnDetail:true}))?.record;
  }
  async function editRecord(original = {}) {
    const input = (title, value, required = false) => vscode.window.showInputBox({title,value:value || '',ignoreFocusOut:true,
      validateInput:value => required && !value.trim() ? '不能为空' : undefined});
    const name = await input('元素名称', original.name, true); if (name === undefined) return;
    const group = await input('元素分组', original.group || '默认', true); if (group === undefined) return;
    const xpath = await input('XPath', original.xpath, true); if (xpath === undefined) return;
    const url = await input('所属页面 URL（可留空）', original.url); if (url === undefined) return;
    const description = await input('元素描述（可留空）', original.description); if (description === undefined) return;
    const result = await api('/api/elements/save', {record:{...original,name,group,xpath,url,description}});
    await refresh(); return result.item;
  }
  async function insertElement(node) {
    const record = await chooseElement(node); if (!record) return;
    const code = core.elementCode(record, settings());
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python') {
      await vscode.window.showTextDocument(await vscode.workspace.openTextDocument({language:'python',content:code})); return;
    }
    // 插入普通文本，防止元素名称中的 $ 被解释为代码片段占位符。
    await editor.edit(edit => edit.replace(editor.selection, code));
  }
  async function start() {
    const result = await manager.start(await pythonExecutable(vscode.window.activeTextEditor?.document.uri), settings());
    output.appendLine(result.owned ? '本扩展的浏览器服务已启动。' : '已连接现有 XPath Studio 服务（不会停止外部服务）。');
    await refresh(); return result;
  }
  async function saveLastPick() { const {payload} = await api('/api/bridge/last'); return editRecord(core.pickedRecord(payload)); }
  async function pick() {
    if (picking) throw new Error('已有抓取进行中，请先完成或取消');
    picking = true;
    try {
      const before = (await api('/api/health')).bridge?.lastPickAt || 0;
      await api('/api/bridge/pick', {});
      const payload = await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,
        title:'WBot：切换到网页，Ctrl＋左键锁定元素，Enter 确认',cancellable:true}, async (_progress, token) => {
        const end = Date.now() + 120000;
        while (Date.now() < end && !token.isCancellationRequested) {
          const health = await api('/api/health');
          if ((health.bridge?.lastPickAt || 0) > before) return (await api('/api/bridge/last')).payload;
          await new Promise(resolve => setTimeout(resolve, 500));
        }
        if (!token.isCancellationRequested) throw new Error('抓取等待超时，请确认扩展已连接并重试');
      });
      if (payload) return editRecord(core.pickedRecord(payload));
    } finally { picking = false; await api('/api/bridge/stop', {}).catch(() => {}); }
  }
  async function validateElement(node) {
    const record = await chooseElement(node); if (!record) return;
    const {payload} = await api('/api/bridge/last');
    if (!payload?.frame?.documentId || !payload.browserId) throw new Error('请先在对应网页重新抓取元素');
    if (!core.scopeMatches(record, payload)) throw new Error('该元素来自其他页面或框架，请先在对应页面重新抓取');
    const result = await api('/api/bridge/validate', {action:'validate',xpath:record.xpath,target:{...payload.frame,browserId:payload.browserId}});
    if (!result.valid) throw new Error(result.error || 'XPath 无效');
    vscode.window.showInformationMessage(`「${record.name}」匹配 ${result.count} 个节点，已高亮 ${result.highlighted || 0} 个元素。`);
    return result;
  }
  async function taskForFile(debug = false) {
    const document = vscode.window.activeTextEditor?.document;
    if (!document || document.languageId !== 'python' || document.uri.scheme !== 'file') throw new Error('请打开并保存一个本机 Python 文件');
    if (!await document.save()) return;
    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
    if (!folder) throw new Error('请先将脚本所在文件夹作为工作区打开');
    const cfg = settings(document.uri), python = await pythonExecutable(document.uri);
    const env = {WBOT_ELEMENT_LIBRARY:cfg.libraryPath, WBOT_BRIDGE_URL:cfg.baseUrl, PYTHONIOENCODING:'utf-8'};
    if (debug) {
      if (!vscode.extensions.getExtension('ms-python.debugpy')) throw new Error('调试需要安装 Microsoft Python Debugger 扩展');
      return vscode.debug.startDebugging(folder, {type:'debugpy',request:'launch',name:'WBot: '+path.basename(document.fileName),
        program:document.fileName,python,cwd:folder.uri.fsPath,console:'integratedTerminal',justMyCode:true,args:cfg.scriptArgs,env});
    }
    const task = new vscode.Task({type:'wbot',file:document.fileName},folder,'运行 '+path.basename(document.fileName),'WBot',
      new vscode.ProcessExecution(python,[document.fileName,...cfg.scriptArgs],{cwd:folder.uri.fsPath,env}));
    task.presentationOptions = {reveal:vscode.TaskRevealKind.Always,panel:vscode.TaskPanelKind.Dedicated,clear:true};
    return vscode.tasks.executeTask(task);
  }
  async function installRuntime() {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) throw new Error('请先打开一个本机项目文件夹');
    const python = await pythonExecutable(vscode.window.activeTextEditor?.document.uri);
    const wheel = path.join(runtime, 'wheels/wbot-0.1.0-py3-none-any.whl');
    const task = new vscode.Task({type:'wbot',action:'install'},folder,'安装 wbot','WBot',
      new vscode.ProcessExecution(python,['-m','pip','install',wheel],{cwd:folder.uri.fsPath}));
    task.presentationOptions = {reveal:vscode.TaskRevealKind.Always};
    return vscode.tasks.executeTask(task);
  }
  async function prepareBrowserExtension() {
    // 释放到稳定全局目录，仅修改副本端口，不改打包资源或用户的浏览器配置。
    const dest = path.join(context.globalStorageUri.fsPath,'browser-extension');
    await fs.mkdir(dest,{recursive:true});
    await fs.cp(path.join(runtime,'extension'),dest,{recursive:true});
    const file = path.join(dest,'background.js');
    const source = await fs.readFile(file,'utf8');
    await fs.writeFile(file,source.replace('var DEFAULT_BRIDGE = "http://127.0.0.1:8790";',`var DEFAULT_BRIDGE = ${JSON.stringify(settings().baseUrl)};`));
    await vscode.env.clipboard.writeText(dest);
    await vscode.commands.executeCommand('revealFileInOS',vscode.Uri.file(path.join(dest,'manifest.json')));
    vscode.window.showInformationMessage('目录已复制。请到 chrome://extensions 或 edge://extensions 开启开发者模式，加载此目录；更新后重新加载扩展并刷新网页。');
    return dest;
  }
  async function newScript() {
    const folder = vscode.workspace.workspaceFolders?.[0];
    const uri = await vscode.window.showSaveDialog({defaultUri:folder && vscode.Uri.joinPath(folder.uri,'wbot_script.py'),filters:{Python:['py']}});
    if (!uri) return;
    if (uri.scheme !== 'file') throw new Error('仅支持本机脚本文件');
    // 保存框之外也防止覆盖已有脚本。
    await fs.writeFile(uri.fsPath,core.scriptTemplate(settings(uri)),{flag:'wx'});
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri));
  }
  flows = new FlowEditor(context,{trusted,settings,pythonExecutable,api,output});
  context.subscriptions.push(flows,vscode.window.registerCustomEditorProvider('wbot.flowEditor',flows,
    {webviewOptions:{retainContextWhenHidden:true},supportsMultipleEditorsPerDocument:false}));
  const handlers = {
    newFlow:() => flows.newFlow(),
    startBridge:start, stopBridge:async () => { const stopped = await manager.stop(); await refresh(true);
      vscode.window.showInformationMessage(stopped ? '已停止本扩展启动的服务' : '没有本扩展启动的服务；外部服务保持运行'); },
    refresh:() => refresh(), pick, saveLastPick, addElement:() => editRecord(),
    editElement:async node => { const record = await chooseElement(node); if (record) return editRecord(record); },
    deleteElement:async node => { const record = await chooseElement(node); if (!record) return;
      if (await vscode.window.showWarningMessage(`删除「${record.group} / ${record.name}」？`,{modal:true},'删除') !== '删除') return;
      await api('/api/elements/delete',{id:record.id}); await refresh(); },
    insertElement, copyXPath:async node => { const record = await chooseElement(node); if (record) await vscode.env.clipboard.writeText(record.xpath); },
    validateElement, search:async () => { const value = await vscode.window.showInputBox({title:'搜索元素（留空显示全部）',value:query});
      if (value !== undefined) { query = value; view.message = query ? `搜索：${query}` : `${records.length} 个元素`; changes.fire(); } },
    importElements:async () => {
      const uris = await vscode.window.showOpenDialog({canSelectMany:false,filters:{JSON:['json']}}); if (!uris?.length) return;
      const bytes = await vscode.workspace.fs.readFile(uris[0]); if (bytes.length > 1900000) throw new Error('导入文件不能超过 1.9 MB');
      const data = JSON.parse(Buffer.from(bytes).toString('utf8').replace(/^\uFEFF/,''));
      const choice = await vscode.window.showQuickPick([{label:'冲突时停止',value:'error'},{label:'跳过同名元素',value:'skip'},{label:'替换同名元素',value:'replace'}]); if (!choice) return;
      const result = await api('/api/elements/import',{data,conflict:choice.value}); await refresh();
      vscode.window.showInformationMessage(`导入完成：新增 ${result.result.inserted}，替换 ${result.result.replaced}，跳过 ${result.result.skipped}`);
    },
    exportElements:async () => { const result = await api('/api/elements/export');
      const uri = await vscode.window.showSaveDialog({saveLabel:'导出',filters:{JSON:['json']}}); if (!uri) return;
      await vscode.workspace.fs.writeFile(uri,Buffer.from(JSON.stringify(result.data,null,2))); },
    newScript, runFile:() => taskForFile(), debugFile:() => taskForFile(true), installRuntime,
    selectPython:async () => { const uris = await vscode.window.showOpenDialog({title:'选择 Python 可执行文件',canSelectMany:false,canSelectFolders:false});
      if (uris?.[0]) await vscode.workspace.getConfiguration('wbot').update('pythonPath',uris[0].fsPath,vscode.ConfigurationTarget.Global); },
    browserExtension:prepareBrowserExtension,
    openWorkbench:() => vscode.env.openExternal(vscode.Uri.parse(settings().baseUrl)),
    showOutput:() => output.show(),
    help:async () => {
      let file = path.join(context.extensionPath,'README.md');
      try { await fs.access(file); } catch { file = path.join(context.extensionPath,'readme.md'); }
      return vscode.commands.executeCommand('markdown.showPreview',vscode.Uri.file(file));
    }
  };
  for (const [name, handler] of Object.entries(handlers)) {
    context.subscriptions.push(vscode.commands.registerCommand('wbot.'+name, async (...args) => {
      try { trusted(); return await handler(...args); }
      catch (error) { output.appendLine(error.stack || String(error)); vscode.window.showErrorMessage('WBot: '+error.message); return undefined; }
    }));
  }
  context.subscriptions.push(output,view,status,changes,{dispose:() => manager.dispose()},
    vscode.workspace.onDidChangeConfiguration(event => { if (event.affectsConfiguration('wbot')) refresh(true); }));
  if (vscode.workspace.isTrusted && !vscode.env.remoteName) refresh(true);
  // 供集成测试与其他扩展只读查看状态；不添加隐藏的执行命令。
  return {refresh, getElements:() => structuredClone(records), provider, bridge:manager, flows};
}
async function deactivate() { if (flows) await flows.dispose(); if (manager) await manager.stop(); }
module.exports = {activate,deactivate};
