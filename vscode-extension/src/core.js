'use strict';
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

function bridgeUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('浏览器服务地址无效'); }
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password ||
      url.search || url.hash || url.pathname !== '/') throw new Error('只允许 http://127.0.0.1:端口，不含用户名、路径或查询参数');
  return url.origin;
}
function libraryPath(value) {
  if (!value) return path.join(os.homedir(), '.xpath_studio', 'elements.sqlite3');
  if (value.startsWith('~/') || value.startsWith('~\\')) value = path.join(os.homedir(), value.slice(2));
  if (!path.isAbsolute(value)) throw new Error('wbot.libraryPath 必须为绝对路径');
  return value;
}
function pyString(value) { return JSON.stringify(String(value)).replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029'); }
function elementCode(record, options) {
  return 'from wbot import web, selector\n\n' +
    `browser = web.get(base_url=${pyString(bridgeUrl(options.baseUrl))})\n` +
    `elements = selector.SelectorStore(${pyString(libraryPath(options.libraryPath))})\n` +
    `element = browser.find(elements.get(${pyString(record.name)}, group=${pyString(record.group)}), timeout=10)\n` +
    'print(element.get_text())\n';
}
function scriptTemplate(options) {
  return '# 先在 WBot 侧栏抓取元素，再插入命名元素调用代码。\n' +
    'from wbot import web, selector\n\n' +
    `browser = web.get(base_url=${pyString(bridgeUrl(options.baseUrl))})\n` +
    `elements = selector.SelectorStore(${pyString(libraryPath(options.libraryPath))})\n\n` +
    'print("已连接：", browser.get_url())\n' +
    '# element = browser.find(elements.get("元素名称", group="默认"))\n' +
    '# print(element.get_text())\n';
}
function pickedRecord(payload) {
  if (!payload || typeof payload.xpath !== 'string' || !payload.xpath.trim()) throw new Error('尚无有效抓取结果');
  return {name: String(payload.text || payload.id || payload.tag || '新元素').slice(0, 200), group: '默认',
    xpath: payload.xpath, description: '', url: payload.frame?.url || payload.url || '', frame: payload.frame || null};
}
function scopeMatches(record, payload) {
  const frame = payload?.frame || {};
  if (record.url && record.url !== (frame.url || payload?.url)) return false;
  return ['frameId', 'isTop', 'topUrl'].every(key => record.frame?.[key] == null || record.frame[key] === frame[key]);
}
function request(base, endpoint, body, timeout = 10000) {
  if (!/^\/api\//.test(endpoint) || endpoint.includes('://')) return Promise.reject(new Error('接口路径无效'));
  const url = new URL(endpoint, bridgeUrl(base));
  const data = body === undefined ? null : Buffer.from(JSON.stringify(body));
  if (data && data.length > 2 * 1024 * 1024) return Promise.reject(new Error('请求超过 2 MiB'));
  return new Promise((resolve, reject) => {
    const req = http.request(url, {method: data ? 'POST' : 'GET',
      headers: data ? {'Content-Type':'application/json','Content-Length':data.length} : {}}, res => {
      let size = 0; const chunks = [];
      res.on('data', chunk => { size += chunk.length; if (size > 16 * 1024 * 1024) req.destroy(new Error('响应超过 16 MiB')); else chunks.push(chunk); });
      res.on('error', reject);
      res.on('end', () => {
        let value;
        try { value = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
        catch { reject(new Error(`服务返回的不是 JSON（HTTP ${res.statusCode}）`)); return; }
        if (res.statusCode !== 200 || !value || value.ok !== true) reject(new Error(value?.error || `服务请求失败（HTTP ${res.statusCode}）`));
        else resolve(value);
      });
    });
    const timer = setTimeout(() => req.destroy(new Error('本机服务请求超时')), timeout);
    req.once('close', () => clearTimeout(timer));
    req.on('error', error => reject(new Error(`无法访问 ${base}：${error.message}。请启动服务或检查端口。`)));
    req.end(data);
  });
}
module.exports = {bridgeUrl, libraryPath, pyString, elementCode, scriptTemplate, pickedRecord, scopeMatches, request};
