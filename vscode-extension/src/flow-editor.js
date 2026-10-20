'use strict';
const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const model = require('../media/flow-model');

class FlowEditor {
  constructor(context, services) { this.context = context; this.services = services; this.sessions = new Set(); }
  async newFlow() {
    this.services.trusted();
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) throw new Error('请先打开本机工作区文件夹');
    const uri = await vscode.window.showSaveDialog({defaultUri:vscode.Uri.joinPath(folder.uri,'我的流程.wbot.json'),filters:{'WBot 流程':['wbot.json']}});
    if (!uri) return;
    if (uri.scheme !== 'file' || !uri.fsPath.endsWith('.wbot.json')) throw new Error('请保存为本机 .wbot.json 文件');
    await fs.writeFile(uri.fsPath,JSON.stringify(model.sample(),null,2)+'\n',{flag:'wx'});
    await vscode.commands.executeCommand('vscode.openWith',uri,'wbot.flowEditor');
  }
  async resolveCustomTextEditor(document, panel) {
    this.services.trusted();
    const media = vscode.Uri.joinPath(this.context.extensionUri,'media');
    panel.webview.options = {enableScripts:true,localResourceRoots:[media]};
    const nonce = crypto.randomBytes(20).toString('hex');
    let html = await fs.readFile(path.join(media.fsPath,'flow-editor.html'),'utf8');
    html = html.replaceAll('__CSP_SOURCE__',panel.webview.cspSource).replaceAll('__NONCE__',nonce);
    for (const name of ['flow-editor.css','flow-model.js','flow-editor.js']) {
      html = html.replaceAll(`__${name}__`,panel.webview.asWebviewUri(vscode.Uri.joinPath(media,name)).toString());
    }
    const session = {document,panel,child:null,starting:false,disposed:false,paused:false,
      debugging:false,controlPending:null,runFlow:null,latestVariables:null,pauseEvent:null};
    this.sessions.add(session);
    const post = data => { if (!session.disposed) panel.webview.postMessage(data); };
    const update = () => {
      try { post({type:'document',flow:session.runFlow || model.validate(JSON.parse(document.getText())),version:document.version,dirty:document.isDirty}); }
      catch (error) { post({type:'invalid',error:'流程文件无效：'+error.message}); }
    };
    session.update = update;
    const subscription = vscode.workspace.onDidChangeTextDocument(event => {
      if (event.document.uri.toString() === document.uri.toString()) update();
    });
    const saved = vscode.workspace.onDidSaveTextDocument(doc => { if (doc.uri.toString() === document.uri.toString()) update(); });
    let queue = Promise.resolve();
    panel.webview.onDidReceiveMessage(message => {
      // 调试控制不排在慢速元素库请求后；停止也可取消尚在准备中的运行。
      if (message && ['pause','resume','step','stop'].includes(message.type)) {
        Promise.resolve().then(() => {
          this.services.trusted();
          if (session.disposed) return;
          return message.type === 'stop' ? this.stop(session) : this.control(session,message,post);
        }).catch(error => post({type:'error',error:error.message}));
        return;
      }
      // 按消息顺序应用编辑；版本不一致时回读真实文档，避免覆盖外部编辑。
      queue = queue.then(async () => {
        this.services.trusted();
        if (session.disposed || !message || typeof message.type !== 'string') return;
        if (message.type === 'ready') {
          update();
          post({type:'runState',running:!!session.child || session.starting,debugging:session.debugging,starting:session.starting});
          if (session.latestVariables) post({type:'event',...session.latestVariables});
          if (session.paused && session.pauseEvent) post({type:'event',...session.pauseEvent});
        }
        else if (message.type === 'edit') {
          if (session.child || session.starting) throw new Error('请先停止运行，再编辑流程');
          if (message.version !== document.version) { update(); throw new Error('文档已在其他位置更新，请重试本次修改'); }
          const flow = model.validate(message.flow);
          const edit = new vscode.WorkspaceEdit();
          edit.replace(document.uri,new vscode.Range(0,0,document.lineCount,0),JSON.stringify(flow,null,2)+'\n');
          if (!await vscode.workspace.applyEdit(edit)) throw new Error('无法应用流程修改');
        } else if (message.type === 'save') { await document.save(); update(); }
        else if (message.type === 'run' || message.type === 'debug') await this.run(session,post,message.type === 'debug');
        else if (message.type === 'undo' || message.type === 'redo') {
          if (session.child || session.starting) throw new Error('请先停止运行');
          await vscode.commands.executeCommand(message.type);
        } else if (message.type === 'source') {
          await vscode.window.showTextDocument(document,vscode.ViewColumn.Beside);
        } else if (message.type === 'elements') {
          post({type:'elements',items:(await this.services.api('/api/elements')).items});
        } else if (message.type === 'pick') {
          await vscode.commands.executeCommand('wbot.pick');
          post({type:'elements',items:(await this.services.api('/api/elements')).items});
        }
      }).catch(error => post({type:'error',error:error.message}));
    });
    panel.onDidDispose(() => {
      session.disposed = true; subscription.dispose(); saved.dispose();
      this.sessions.delete(session); void this.stop(session);
    });
    panel.webview.html = html;
  }
  async run(session, post, debugging = false) {
    this.services.trusted();
    if (session.child || session.starting) throw new Error('此流程正在运行');
    const doc = session.document;
    const folder = vscode.workspace.getWorkspaceFolder(doc.uri);
    if (doc.uri.scheme !== 'file' || !folder) throw new Error('请将流程保存在当前本机工作区内');
    const flow = model.validate(JSON.parse(doc.getText()));
    session.starting = true;
    session.cancelStart = false;
    session.paused = false;
    session.debugging = debugging;
    session.controlPending = null;
    session.pauseEvent = null;
    session.latestVariables = null;
    session.runFlow = flow;
    post({type:'runState',running:true,debugging,starting:true});
    try {
      if (!await doc.save()) throw new Error('流程尚未保存');
      const python = await this.services.pythonExecutable(doc.uri);
      if (session.disposed || session.cancelStart) {
        session.runFlow = null;
        post({type:'event',event:'stopped'});
        post({type:'runState',running:false,debugging});
        session.update();
        return;
      }
      const cfg = this.services.settings(doc.uri);
      const args = ['-I','-X','utf8','-u',path.join(this.context.extensionPath,'runtime/flow_runner.py')];
      if (debugging) args.push('--debug');
      const child = spawn(python,args,
        {cwd:folder.uri.fsPath,windowsHide:true,shell:false,stdio:['pipe','pipe','pipe'],
          env:{...process.env,WBOT_ELEMENT_LIBRARY:cfg.libraryPath,WBOT_BRIDGE_URL:cfg.baseUrl}});
      session.child = child;
      session.starting = false;
      post({type:'runState',running:true,debugging,starting:false});
      let buffer = '', terminal = false;
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', text => {
        buffer += text;
        let end;
        while ((end = buffer.indexOf('\n')) !== -1) {
          const line = buffer.slice(0,end); buffer = buffer.slice(end+1);
          try {
            const event = JSON.parse(line);
            if (event.event === 'variables') session.latestVariables = event;
            if (event.event === 'paused') { session.paused = true; session.controlPending = null; session.pauseEvent = event; }
            if (event.event === 'continued') { session.paused = false; session.controlPending = null; session.pauseEvent = null; }
            if (['finished','failed','stopped'].includes(event.event)) {
              terminal = true; session.paused = false; session.pauseEvent = null; session.controlPending = null;
            }
            post({type:'event',...event});
          } catch { this.services.output.appendLine(line); }
        }
      });
      child.stderr.setEncoding('utf8');
      child.stderr.on('data', text => { this.services.output.append(text); post({type:'error',error:text.slice(-2000)}); });
      child.stdin.on('error', () => {});
      child.once('error', error => { terminal = true; post({type:'event',event:'failed',error:error.message}); });
      child.once('close', code => {
        if (session.child === child) session.child = null;
        if (!terminal) post({type:'event',event:session.stopping ? 'stopped' : 'failed',error:`Python 进程退出（${code}）`});
        session.stopping = false;
        session.paused = false; session.controlPending = null; session.pauseEvent = null; session.runFlow = null;
        post({type:'runState',running:false,debugging});
        session.update();
      });
      child.stdin.write(JSON.stringify(flow)+'\n');
    } catch (error) { session.runFlow = null; post({type:'runState',running:false,debugging}); session.update(); throw error; }
    finally { session.starting = false; }
  }
  control(session, message, post) {
    const child = session.child;
    if (!child || child.exitCode !== null || session.stopping || !child.stdin.writable)
      throw new Error('流程尚未启动或已经结束');
    const action = message.type;
    if (session.controlPending) return;
    if (action === 'pause') {
      if (session.paused) return;
      session.controlPending = 'pause';
      child.stdin.write('pause\n');
      return;
    }
    if (!session.paused || !session.pauseEvent || message.pauseId !== session.pauseEvent.pauseId) {
      // 旧页面或重复消息不推进执行；回放真实状态供界面恢复。
      if (session.paused && session.pauseEvent) post({type:'event',...session.pauseEvent});
      return;
    }
    session.controlPending = action;
    session.paused = false;
    child.stdin.write(`${action} ${message.pauseId}\n`);
  }
  async stop(session) {
    if (session.starting) session.cancelStart = true;
    const child = session.child;
    if (!child) return;
    session.stopping = true;
    await new Promise(resolve => {
      if (child.exitCode !== null) return resolve();
      const timer = setTimeout(() => { child.kill(); resolve(); },2000);
      child.once('close', () => { clearTimeout(timer); resolve(); });
      child.stdin.end('stop\n');
    });
  }
  async dispose() { await Promise.all([...this.sessions].map(session => this.stop(session))); }
}
module.exports = {FlowEditor};
