'use strict';
const {spawn} = require('node:child_process');
const path = require('node:path');
const {bridgeUrl, libraryPath, request} = require('./core');

class BridgeManager {
  constructor(runtime, log = () => {}) { this.runtime = runtime; this.log = log; this.child = null; this.starting = null; }
  start(python, config) {
    if (this.starting) return this.starting;
    this.starting = this._start(python, config).finally(() => { this.starting = null; });
    return this.starting;
  }
  async _start(python, config) {
    const base = bridgeUrl(config.baseUrl);
    try {
      const health = await request(base, '/api/health', undefined, 1200);
      if (!health.wbot) throw new Error('该端口运行旧版 XPath Studio，请升级到 1.4.0 或换端口');
      return {owned:!!this.child, health};
    } catch (error) {
      if (error.message.includes('旧版')) throw error;
    }
    if (this.child) throw new Error('本扩展的服务仍在运行；修改端口或解释器后，请先停止再启动');
    const port = Number(new URL(base).port || 80);
    const child = spawn(python, ['-I', '-X', 'utf8', '-u', path.join(this.runtime, 'bridge_server.py'), '--port', String(port)], {
      cwd:this.runtime, windowsHide:true, shell:false, stdio:['pipe','pipe','pipe'],
      env:{...process.env, WBOT_ELEMENT_LIBRARY:libraryPath(config.libraryPath), PYTHONIOENCODING:'utf-8'}
    });
    this.child = child;
    let errors = '';
    child.stderr.on('data', data => { errors = (errors + data.toString('utf8')).slice(-6000); this.log(data.toString('utf8')); });
    child.once('exit', () => { if (this.child === child) this.child = null; });
    try {
      await new Promise((resolve, reject) => {
        let buffer = '';
        const timer = setTimeout(() => reject(new Error('启动浏览器服务超时\n' + errors)), 15000);
        const finish = fn => value => { clearTimeout(timer); fn(value); };
        child.once('error', finish(reject));
        child.once('exit', finish(code => reject(new Error(`浏览器服务已退出（${code}）\n${errors}`))));
        child.stdout.on('data', data => {
          buffer += data.toString('utf8'); this.log(data.toString('utf8'));
          if (buffer.includes('__WBOT_BRIDGE__')) finish(resolve)();
          if (buffer.length > 65536) buffer = buffer.slice(-4096);
        });
      });
      return {owned:true, health:await request(base, '/api/health')};
    } catch (error) { await this.stop(); throw error; }
  }
  async stop() {
    const child = this.child;
    if (!child) return false;
    await new Promise(resolve => {
      if (child.exitCode !== null) { resolve(); return; }
      const timer = setTimeout(() => { if (child.exitCode === null) child.kill(); resolve(); }, 3000);
      child.once('exit', () => { clearTimeout(timer); resolve(); });
      child.stdin.on('error', () => {});
      child.stdin.end('stop\n');
    });
    if (this.child === child) this.child = null;
    return true;
  }
  dispose() { return this.stop(); }
}
module.exports = {BridgeManager};
