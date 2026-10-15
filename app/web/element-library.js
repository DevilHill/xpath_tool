/* 可持久化的元素库；用户内容始终通过 textContent / value 显示。 */
(() => {
  'use strict';
  const root = document.getElementById('elementLibrary');
  if (!root) return;
  root.classList.add('el-library');
  root.innerHTML = `
    <div class="el-heading"><div><h3>元素库</h3><p>保存定位器、按组管理，并在 wbot Python 脚本中复用。</p></div>
      <button type="button" class="btn primary" data-el="capture">保存当前 XPath</button></div>
    <div class="el-toolbar">
      <label class="el-search">搜索元素<input data-el="search" type="search" placeholder="名称、XPath 或描述" maxlength="8192"></label>
      <label>分组<select data-el="group"><option value="">全部分组</option></select></label>
      <button type="button" class="btn" data-el="refresh">刷新</button>
      <button type="button" class="btn" data-el="export">导出 JSON</button>
      <label>导入同名元素<select data-el="conflict"><option value="error">冲突时停止</option><option value="skip">跳过</option><option value="replace">替换</option></select></label>
      <button type="button" class="btn" data-el="import">导入 JSON</button>
      <input data-el="file" type="file" accept=".json,application/json" hidden>
    </div>
    <p data-el="status" class="el-status" role="status" aria-live="polite"></p>
    <div data-el="list" class="el-items"></div>
    <dialog data-el="dialog" class="el-dialog"><form data-el="form">
      <div class="el-heading"><h3 data-el="title">保存元素</h3><button type="button" class="btn" data-el="cancel" aria-label="关闭元素编辑">关闭</button></div>
      <label>名称<input data-el="name" required maxlength="200" autocomplete="off"></label>
      <label>分组<input data-el="edit-group" required maxlength="200" list="wbot-element-groups"><datalist id="wbot-element-groups"></datalist></label>
      <label>XPath<textarea data-el="xpath" required maxlength="8192" rows="3" spellcheck="false"></textarea></label>
      <label>页面 URL<input data-el="url" maxlength="8192" type="text"></label>
      <label>描述<textarea data-el="description" maxlength="10000" rows="2"></textarea></label>
      <p data-el="frame" class="el-frame"></p>
      <p data-el="error" class="el-error" role="alert"></p>
      <div class="el-form-actions"><button type="submit" class="btn primary" data-el="submit">保存元素</button></div>
    </form></dialog>`;
  const $ = (key) => root.querySelector(`[data-el="${key}"]`);
  let items = [], editing = null, request = 0, busy = false;
  const status = (text, error = false) => {
    $('status').textContent = text;
    $('status').classList.toggle('el-error', error);
  };
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    let data;
    try { data = await response.json(); } catch (_) { throw new Error(`服务响应无效（${response.status}）`); }
    if (!response.ok || !data.ok) throw new Error(data.error || data.message || `请求失败（${response.status}）`);
    return data;
  }
  function button(label, action) {
    const element = document.createElement('button');
    element.type = 'button'; element.className = 'btn'; element.textContent = label;
    element.addEventListener('click', () => Promise.resolve().then(action).catch(error => status(error.message, true)));
    return element;
  }
  async function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return; } catch (_) { /* 嵌入式窗口可禁用剪贴板 API */ }
    }
    const input = document.createElement('textarea');
    input.value = text; input.className = 'el-copy-helper'; document.body.append(input);
    input.select();
    const copied = document.execCommand('copy'); input.remove();
    if (!copied) throw new Error('无法访问剪贴板，请检查窗口权限');
  }
  function render() {
    const query = $('search').value.toLocaleLowerCase(), group = $('group').value;
    const shown = items.filter(item => (!group || item.group === group) &&
      [item.name, item.xpath, item.description].some(value => String(value || '').toLocaleLowerCase().includes(query)));
    $('list').replaceChildren();
    if (!shown.length) {
      const empty = document.createElement('p'); empty.className = 'el-empty';
      empty.textContent = items.length ? '没有符合筛选条件的元素。' : '还没有保存的元素。抓取网页元素后，点击「保存当前 XPath」。';
      $('list').append(empty);
    }
    for (const item of shown) {
      const card = document.createElement('article'); card.className = 'el-card';
      const heading = document.createElement('div'); heading.className = 'el-card-heading';
      const title = document.createElement('strong'); title.textContent = item.name;
      const tag = document.createElement('span'); tag.className = 'el-group-tag'; tag.textContent = item.group;
      heading.append(title, tag);
      const xpath = document.createElement('code'); xpath.textContent = item.xpath;
      const detail = document.createElement('p'); detail.className = 'el-detail';
      detail.textContent = item.description || item.url || '未填写描述';
      const actions = document.createElement('div'); actions.className = 'el-card-actions';
      actions.append(button('使用', () => {
        if (!window.XPSWorkbench?.useElement) throw new Error('工作台尚未就绪');
        window.XPSWorkbench.useElement(item);
        status(`已载入「${item.name}」；请在正确的页面和框架中校验。`);
      }), button('编辑', () => edit(item)), button('复制 wbot 代码', async () => {
        const py = value => JSON.stringify(String(value));
        const code = `from wbot import web, selector\n\nelements = selector.SelectorStore()\nbrowser = web.get(base_url=${py(window.location.origin)})\nelement = browser.find(elements.get(${py(item.name)}, group=${py(item.group)}))\nprint(element.get_text())\n`;
        await copy(code); status('已复制 wbot 代码；默认连接本机 XPath Studio 中的浏览器。');
      }), button('删除', async () => {
        if (!window.confirm(`删除元素「${item.group} / ${item.name}」？此操作不可撤销。`)) return;
        await api('/api/elements/delete', {id: item.id}); await refresh(); status(`已删除「${item.name}」。`);
      }));
      card.append(heading, xpath, detail, actions); $('list').append(card);
    }
    $('list').setAttribute('aria-label', `${shown.length} 个元素`);
  }
  async function refresh() {
    const generation = ++request;
    status('正在加载元素库…');
    const data = await api('/api/elements');
    if (generation !== request) return;
    items = data.items;
    const selected = $('group').value;
    $('group').replaceChildren(new Option('全部分组', ''));
    root.querySelector('#wbot-element-groups').replaceChildren();
    for (const group of [...new Set(items.map(item => item.group))].sort()) {
      $('group').add(new Option(group, group));
      root.querySelector('#wbot-element-groups').append(new Option(group, group));
    }
    $('group').value = [...$('group').options].some(option => option.value === selected) ? selected : '';
    render(); status(`已加载 ${items.length} 个元素。`);
  }
  function edit(item) {
    editing = {...item};
    $('title').textContent = item.id ? '编辑元素' : '保存当前 XPath';
    for (const key of ['name', 'xpath', 'url', 'description']) $(key).value = item[key] || '';
    $('edit-group').value = item.group || $('group').value || '默认';
    $('frame').textContent = item.frame
      ? '已保留抓取时的框架上下文。页面导航后需重新抓取或确认框架，不能将临时 frameId 当作跨会话定位链。'
      : '未附带框架上下文。跨 iframe 元素需要先确认其所在框架。';
    $('error').textContent = '';
    $('dialog').showModal(); $('name').focus();
  }
  $('capture').addEventListener('click', () => {
    try {
      const current = window.XPSWorkbench?.getCurrent?.();
      if (!current?.xpath?.trim()) throw new Error('请先抓取元素或输入有效的 XPath。');
      edit(current);
    } catch (error) { status(error.message, true); }
  });
  $('cancel').addEventListener('click', () => { if (!busy) $('dialog').close(); });
  $('dialog').addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  $('form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    busy = true; $('submit').disabled = true; $('error').textContent = '';
    try {
      const record = {...editing, name: $('name').value, group: $('edit-group').value,
        xpath: $('xpath').value, url: $('url').value, description: $('description').value};
      await api('/api/elements/save', {record});
      $('dialog').close(); await refresh(); status(`已保存「${record.name}」。`);
    } catch (error) { $('error').textContent = error.message; }
    finally { busy = false; $('submit').disabled = false; }
  });
  $('search').addEventListener('input', render); $('group').addEventListener('change', render);
  $('refresh').addEventListener('click', () => refresh().catch(error => status(error.message, true)));
  $('export').addEventListener('click', async () => {
    try {
      const result = await api('/api/elements/export');
      const url = URL.createObjectURL(new Blob([JSON.stringify(result.data, null, 2)], {type: 'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = 'wbot-elements.json';
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      status('元素库 JSON 已导出。');
    } catch (error) { status(error.message, true); }
  });
  $('import').addEventListener('click', () => $('file').click());
  $('file').addEventListener('change', async () => {
    const file = $('file').files[0]; if (!file) return;
    try {
      if (file.size > 1.9 * 1024 * 1024) throw new Error('导入文件不能超过 1.9 MB');
      const data = JSON.parse(await file.text()), conflict = $('conflict').value;
      if (conflict === 'replace' && !window.confirm('导入将替换冲突的已有元素，确认继续？')) return;
      const response = await api('/api/elements/import', {data, conflict});
      await refresh();
      const result = response.result;
      status(`导入完成：新增 ${result.inserted}，替换 ${result.replaced}，跳过 ${result.skipped}。`);
    } catch (error) { status(`导入失败：${error.message}`, true); }
    finally { $('file').value = ''; }
  });
  window.XPSElementLibrary = {refresh};
  refresh().catch(error => status(`元素库加载失败：${error.message}`, true));
})();
