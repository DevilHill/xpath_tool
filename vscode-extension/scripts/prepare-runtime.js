'use strict';
// 打包现有可运行代码，保持浏览器桥与桌面端使用相同实现。
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..'), dest = path.resolve(__dirname, '../runtime');
function copyTree(source, target, filter) {
  fs.mkdirSync(target, {recursive:true});
  for (const entry of fs.readdirSync(source, {withFileTypes:true})) {
    if (entry.name === '__pycache__' || entry.name.startsWith('.')) continue;
    const src = path.join(source, entry.name), out = path.join(target, entry.name);
    if (entry.isDirectory()) copyTree(src, out, filter);
    else if (filter(entry.name)) fs.copyFileSync(src, out);
  }
}
copyTree(path.join(root, 'app'), path.join(dest, 'app'), name => /\.(py|js|css|html|png|ico)$/.test(name));
copyTree(path.join(root, 'wbot'), path.join(dest, 'wbot'), name => name.endsWith('.py'));
copyTree(path.join(root, 'extension'), path.join(dest, 'extension'), name => /\.(js|json|html|png|svg)$/.test(name));
fs.copyFileSync(path.join(__dirname, 'bridge_server.py'), path.join(dest, 'bridge_server.py'));
fs.copyFileSync(path.join(__dirname, 'flow_runner.py'), path.join(dest, 'flow_runner.py'));
fs.mkdirSync(path.join(dest, 'wheels'), {recursive:true});
fs.copyFileSync(path.join(root, 'dist/wbot/wbot-0.1.0-py3-none-any.whl'), path.join(dest, 'wheels/wbot-0.1.0-py3-none-any.whl'));
fs.copyFileSync(path.join(root, 'LICENSE'), path.resolve(__dirname, '../LICENSE'));
console.log('已准备浏览器服务、wbot 和浏览器扩展运行资源');
