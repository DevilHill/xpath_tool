'use strict';
(() => {
  const M = window.FlowModel, $ = id => document.getElementById(id);
  const vscode = typeof acquireVsCodeApi === 'function' ? acquireVsCodeApi() : null;
  let flow = null, confirmed = null, version = 0, selected = null, pending = false, running = false, invalid = false;
  let history = [], future = [], elements = [], liveValues = {}, states = new Map(), logCount = 0;
  let afterEdit = null, debugging = false, starting = false, pausedId = null, pauseId = null, pauseReason = '', controlPending = null;
  const node = (tag, cls, text) => { const value = document.createElement(tag); if (cls) value.className = cls; if (text !== undefined) value.textContent = text; return value; };
  const notify = text => { $('notice').textContent = text; $('notice').hidden = !text; };
  $('notice').onclick = () => notify('');
  function requestAction(type) {
    if (pending && ['save','run','debug'].includes(type)) { afterEdit = type; return; }
    if (['run','debug'].includes(type) && (running || controlPending || invalid || !flow)) return;
    if (type === 'pause' && (!running || starting || pausedId || controlPending)) return;
    if (['resume','step'].includes(type) && (!running || !pausedId || controlPending)) return;
    if (type === 'stop' && (!running || controlPending === 'stop')) return;
    if (vscode && ['run','debug','pause','resume','step','stop'].includes(type)) { controlPending = type; render(); }
    send(['resume','step'].includes(type) ? {type,pauseId} : {type});
  }
  function showTab(name) {
    document.querySelectorAll('[data-tab]').forEach(button => button.classList.toggle('active',button.dataset.tab === name));
    $('logs').hidden = name !== 'logs'; $('variables').hidden = name !== 'variables';
  }
  function send(message) {
    if (vscode) return vscode.postMessage(message);
    // 独立浏览器页面用于界面预览，不伪装实际执行结果。
    if (message.type === 'edit') { history.push(structuredClone(confirmed)); future = []; receive({type:'document',flow:message.flow,version:version+1,dirty:true}); }
    else if (message.type === 'ready') receive({type:'document',flow:M.sample(),version:1,dirty:false});
    else if (message.type === 'undo' && history.length) { future.push(structuredClone(flow)); receive({type:'document',flow:history.pop(),version:version+1,dirty:true}); }
    else if (message.type === 'redo' && future.length) { history.push(structuredClone(flow)); receive({type:'document',flow:future.pop(),version:version+1,dirty:true}); }
    else if (message.type === 'save') {
      const blob = new Blob([JSON.stringify(flow,null,2)],{type:'application/json'});
      const url = URL.createObjectURL(blob), link = node('a');
      link.href = url; link.download = flow.name.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_')+'.wbot.json'; link.click();
      setTimeout(() => URL.revokeObjectURL(url),1000);
    } else if (message.type !== 'undo' && message.type !== 'redo') notify('浏览器预览仅提供编辑体验。请在 VS Code 安装 WBot Studio 后运行流程、连接元素库或查看 JSON。');
  }
  function edit(mutator) {
    if (!flow || pending || running || controlPending || invalid) return;
    const next = structuredClone(flow);
    try { mutator(next); M.validate(next); }
    catch (error) { notify(error.message); render(); return; }
    flow = next; pending = true; render();
    send({type:'edit',flow:next,version});
  }
  function add(type, before) {
    const item = M.step(type);
    edit(next => {
      const index = before ? next.steps.findIndex(s => s.id === before) : -1;
      next.steps.splice(index < 0 ? next.steps.length : index,0,item);
      selected = item.id;
    });
  }
  function reorder(id,before) {
    if (id === before) return;
    edit(next => {
      const from = next.steps.findIndex(s => s.id === id);
      if (from < 0) return;
      const [item] = next.steps.splice(from,1), to = next.steps.findIndex(s => s.id === before);
      next.steps.splice(to < 0 ? next.steps.length : to,0,item);
    });
  }
  function drop(event,before) {
    event.preventDefault();
    try {
      const data = JSON.parse(event.dataTransfer.getData('text/plain'));
      if (data.type && M.definition(data.type)) add(data.type,before);
      else if (data.id) reorder(data.id,before);
    } catch {}
  }
  function renderCatalog() {
    const query = $('search').value.toLowerCase(), box = $('catalog'); box.replaceChildren();
    const list = M.catalog.filter(d => (d.name+d.group).toLowerCase().includes(query));
    $('command-count').textContent = `${list.length} 个`;
    for (const group of new Set(list.map(d => d.group))) {
      box.append(node('div','category',group));
      for (const def of list.filter(d => d.group === group)) {
        const button = node('button','command'); button.dataset.group = group; button.dataset.type = def.type;
        button.disabled = running || pending || controlPending !== null || invalid; button.draggable = !button.disabled;
        button.append(node('span','command-icon',def.icon),node('span','',def.name));
        button.onclick = () => add(def.type);
        button.ondragstart = e => { e.dataTransfer.setData('text/plain',JSON.stringify({type:def.type})); e.dataTransfer.effectAllowed = 'copy'; };
        box.append(button);
      }
    }
    if (!list.length) box.append(node('p','hint','未找到匹配指令'));
  }
  function summary(step) {
    const p = step.params;
    if (step.type === 'set') return `${p.output} = ${p.value}`;
    if (step.type === 'wait') return `${p.seconds} 秒`;
    if (step.type === 'web.connect') return '绑定最近抓取的标签页与框架';
    if (step.type.startsWith('web.')) return (p.element ? `${p.group} / ${p.element}` : p.xpath || '请选择元素或填写 XPath') + (p.output ? ` → ${p.output}` : '');
    if (step.type.startsWith('file.')) return p.path || '配置文件路径';
    return p.text || '填写指令参数';
  }
  function renderSteps() {
    if (!flow) return;
    $('steps').replaceChildren();
    flow.steps.forEach((step,index) => {
      const def = M.definition(step.type);
      const row = node('div',`step ${step.id === selected ? 'selected' : ''} ${!step.enabled ? 'disabled' : ''} ${states.get(step.id) || ''} ${step.id === pausedId ? 'paused' : ''}`);
      row.dataset.id = step.id; row.tabIndex = 0; row.setAttribute('role','group'); row.setAttribute('aria-label',`${index+1}. ${step.label || def.name}${step.id === pausedId ? '，暂停于执行前' : ''}`);
      const breakpoint = node('button',`breakpoint ${step.breakpoint ? 'active' : ''}`);
      breakpoint.title = `${step.breakpoint ? '移除' : '设置'}第 ${index+1} 条指令断点${!step.enabled ? '（禁用的指令不会暂停）' : ''}`;
      breakpoint.setAttribute('aria-label',breakpoint.title); breakpoint.setAttribute('aria-pressed',String(!!step.breakpoint));
      breakpoint.disabled = running || pending || controlPending !== null || invalid;
      breakpoint.onclick = event => {
        event.stopPropagation();
        edit(next => { const item = next.steps.find(s => s.id === step.id); item.breakpoint = !item.breakpoint; });
      };
      const info = node('div','step-info');
      info.append(node('div','step-title',step.label || def.name),node('div','step-summary',summary(step)));
      if (step.id === pausedId) info.append(node('div','paused-label','→ 下一条执行'));
      const check = node('input'); check.type = 'checkbox'; check.checked = step.enabled; check.disabled = running || pending || controlPending !== null || invalid;
      check.setAttribute('aria-label',`启用第 ${index+1} 条指令`);
      check.onclick = e => e.stopPropagation();
      check.onchange = () => edit(next => { next.steps.find(s => s.id === step.id).enabled = check.checked; });
      row.append(breakpoint,node('span','grip','⠿'),node('span','step-num',String(index+1).padStart(2,'0')),node('span','step-icon',states.get(step.id) === 'done' ? '✓' : def.icon),info,check);
      row.onclick = () => { selected = step.id; render(); };
      row.onkeydown = event => { if (event.target === row && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); selected = step.id; render(); } };
      row.draggable = !running && !pending && !controlPending && !invalid;
      row.ondragstart = event => { event.dataTransfer.setData('text/plain',JSON.stringify({id:step.id})); event.dataTransfer.effectAllowed = 'move'; };
      row.ondragover = event => { event.preventDefault(); row.classList.add('drag-over'); };
      row.ondragleave = () => row.classList.remove('drag-over');
      row.ondrop = event => drop(event,step.id);
      $('steps').append(row);
    });
    $('empty').hidden = !!flow.steps.length;
    $('step-count').textContent = `${flow.steps.length} 条指令 · ${flow.steps.filter(s => s.enabled).length} 条启用 · ${flow.steps.filter(s => s.breakpoint).length} 个断点`;
    $('step-count').title = '点击每条指令左侧圆点设置断点；调试模式在断点处暂停，普通运行忽略断点。';
  }
  function renderProperties() {
    if (!flow) return;
    const box = $('properties'), step = flow.steps.find(s => s.id === selected);
    box.replaceChildren(); $('selected-number').textContent = step ? '#'+String(flow.steps.indexOf(step)+1).padStart(2,'0') : '—';
    if (!step) { box.append(node('div','inspector-empty','选择一条指令，设置参数与输出变量。')); return; }
    const def = M.definition(step.type), body = node('div','properties-body');
    body.append(node('div','property-title',def.name),node('p','',def.description));
    for (const f of [{key:'label',label:'备注名称',type:'text'},...def.fields]) {
      const label = node('label','field'), input = node(f.type === 'area' ? 'textarea' : 'input');
      input.id = 'param-'+f.key;
      if (f.type === 'number') { input.type = 'number'; input.min = 0; input.max = 3600; input.step = '.1'; }
      input.value = f.key === 'label' ? step.label : step.params[f.key];
      input.disabled = running || pending || controlPending !== null || invalid; input.placeholder = f.key === 'label' ? def.name : '';
      input.onchange = () => edit(next => {
        const changed = next.steps.find(s => s.id === step.id);
        if (f.key === 'label') changed.label = input.value;
        else changed.params[f.key] = f.type === 'number' ? Number(input.value) : input.value;
      });
      label.append(node('span','',f.label),input); body.append(label);
    }
    body.append(node('div','hint','文本支持 ${变量名}。输出变量会在指令成功后更新。网页操作前请先连接已抓取的页面。'));
    box.append(body);
  }
  function renderVariables() {
    if (!flow) return;
    const box = $('variable-list'); box.replaceChildren();
    $('variable-count').textContent = Object.keys(running ? liveValues : flow.variables).length;
    $('variables-label').textContent = pausedId ? '暂停时变量 · 只读' : running ? '运行时变量 · 只读' : '初始变量 · 文本类型';
    $('add-variable').disabled = pending || running || controlPending !== null || invalid;
    if (running) {
      if (!Object.keys(liveValues).length) box.append(node('p','hint','当前暂无变量。'));
      for (const [key,value] of Object.entries(liveValues)) box.append(node('div','variable-live',`${key} = ${value}`));
      return;
    }
    for (const [key,value] of Object.entries(flow.variables)) {
      const row = node('div','variable-row'), name = node('input'), val = node('input'), remove = node('button','','×');
      name.value = key; name.setAttribute('aria-label','变量名称 '+key);
      val.value = value; val.setAttribute('aria-label','初始值 '+key);
      name.disabled = val.disabled = remove.disabled = pending || running || controlPending !== null || invalid;
      name.onchange = () => edit(next => {
        if (name.value !== key && Object.hasOwn(next.variables,name.value)) throw new Error('变量名称重复');
        const pairs = Object.entries(next.variables).map(([k,v]) => [k === key ? name.value : k,v]);
        next.variables = Object.fromEntries(pairs);
      });
      val.onchange = () => edit(next => { next.variables[key] = val.value; });
      remove.onclick = () => edit(next => { delete next.variables[key]; });
      row.append(name,val,remove); box.append(row);
    }
    if (Object.keys(liveValues).length) {
      box.append(node('p','hint','最近一次运行的变量值'));
      for (const [key,value] of Object.entries(liveValues)) box.append(node('div','variable-live',`${key} = ${value}`));
    }
  }
  function render() {
    renderCatalog();
    renderDebugStatus();
    if (!flow) {
      document.querySelectorAll('[data-action]').forEach(b => { b.disabled = b.dataset.action === 'stop' ? !running || controlPending === 'stop' : b.dataset.action !== 'source'; });
      $('flow-name').disabled = true;
      return;
    }
    if (!flow.steps.some(s => s.id === selected)) selected = flow.steps[0]?.id;
    $('flow-name').value = flow.name; $('flow-name').disabled = pending || running || controlPending !== null || invalid;
    $('footer-name').textContent = flow.name+' .wbot.json';
    renderSteps(); renderProperties(); renderVariables();
    document.querySelectorAll('[data-action]').forEach(button => {
      const action = button.dataset.action;
      if (action === 'stop') button.disabled = !running || controlPending === 'stop';
      else if (action === 'pause') button.disabled = !running || starting || !!pausedId || !!controlPending;
      else if (['resume','step'].includes(action)) button.disabled = !running || !pausedId || !!controlPending;
      else button.disabled = action === 'source' ? false : invalid || running || !!controlPending || (pending && !['save','run','debug'].includes(action));
      if (['up','down','delete','duplicate'].includes(action) && !selected) button.disabled = true;
    });
    renderElements();
  }
  function renderDebugStatus() {
    const banner = $('debug-status');
    banner.hidden = !running; banner.classList.toggle('is-paused',!!pausedId);
    if (!running) return;
    if (controlPending === 'stop') { banner.textContent = '正在停止流程…'; $('run-status').textContent = '正在停止…'; }
    else if (starting) banner.textContent = '正在准备 Python 运行环境…可点击停止取消启动。';
    else if (controlPending === 'pause') banner.textContent = '已请求暂停：当前指令完成后，在下一条启用指令前暂停。';
    else if (['resume','step'].includes(controlPending)) banner.textContent = controlPending === 'step' ? '正在执行单步…' : '正在继续…';
    else if (pausedId) {
      const index = flow?.steps.findIndex(item => item.id === pausedId) ?? -1;
      const reason = {breakpoint:'命中断点',step:'单步完成',pause:'手动暂停',entry:'开始调试'}[pauseReason] || '已暂停';
      banner.textContent = `${reason} · 第 ${index+1} 条指令尚未执行。可检查变量后单步或继续。`;
    } else banner.textContent = debugging ? '调试中 · 遇到断点会暂停；也可在当前指令完成后暂停。' : '运行中 · 忽略断点；点击暂停可在下一条指令前进入单步执行。';
  }
  function appendLog(text,kind = '') {
    if (!logCount) $('logs').replaceChildren();
    const line = node('div','log '+kind); line.append(node('time','',new Date().toLocaleTimeString('zh-CN',{hour12:false})),node('span','',String(text).slice(0,4000)));
    $('logs').append(line); logCount++;
    if ($('logs').children.length > 500) $('logs').firstChild.remove();
    $('log-count').textContent = String(logCount); $('logs').scrollTop = $('logs').scrollHeight;
  }
  function receive(message) {
    if (message.type === 'document') {
      if (invalid) notify('');
      flow = structuredClone(message.flow); confirmed = structuredClone(flow); version = message.version; pending = false; invalid = false;
      $('saved-state').textContent = message.dirty ? '● 未保存' : '✓ 已保存'; render();
      if (afterEdit) { const action = afterEdit; afterEdit = null; requestAction(action); }
    } else if (message.type === 'invalid') { invalid = true; pending = false; afterEdit = null; flow = null; $('steps').replaceChildren(); $('properties').replaceChildren(); notify(message.error+'；点击「查看 JSON」修复。'); render(); }
    else if (message.type === 'error') {
      afterEdit = null;
      if (controlPending !== 'stop') controlPending = null;
      notify(message.error); appendLog(message.error,'error');
      if (pending) { flow = structuredClone(confirmed); pending = false; }
      render();
    } else if (message.type === 'runState') {
      const wasStarting = starting;
      running = message.running; debugging = !!message.debugging; starting = running && !!message.starting;
      if (!running) { pausedId = null; pauseId = null; pauseReason = ''; controlPending = null; }
      else if (['run','debug'].includes(controlPending)) controlPending = null;
      if (starting) $('run-status').textContent = '准备 Python…';
      else if (running && wasStarting) $('run-status').textContent = debugging ? '调试中' : '运行中';
      render();
    }
    else if (message.type === 'elements') { elements = message.items; renderElements(); }
    else if (message.type === 'event') {
      const event = message.event;
      if (event === 'started') {
        states = new Map(); liveValues = {}; starting = false; pausedId = null; pauseId = null; pauseReason = '';
        if (controlPending !== 'stop') controlPending = null;
        $('run-status').textContent = debugging ? '调试中' : '运行中'; appendLog(`开始${debugging ? '调试' : '执行'}，共 ${message.total} 条指令`); render();
      }
      else if (event === 'paused') {
        starting = false; pausedId = message.id; pauseId = message.pauseId; pauseReason = message.reason; selected = message.id;
        if (controlPending !== 'stop') controlPending = null;
        if (message.values) liveValues = message.values;
        $('run-status').textContent = `已暂停 · 第 ${message.index+1} 条执行前`;
        appendLog(`暂停于第 ${message.index+1} 条指令执行前（${{breakpoint:'断点',step:'单步',pause:'手动暂停',entry:'开始调试'}[message.reason] || '暂停'}）`);
        showTab('variables'); render();
        document.querySelector('.step.paused')?.scrollIntoView({block:'nearest'});
      } else if (event === 'continued') {
        starting = false; pausedId = null; pauseId = null; pauseReason = '';
        if (controlPending !== 'stop') controlPending = null;
        $('run-status').textContent = debugging ? '调试中' : '运行中'; render();
      }
      else if (event === 'step') {
        states.set(message.id,message.state);
        if (message.state === 'running') { selected = message.id; $('run-status').textContent = `正在执行第 ${message.index+1} 条`; }
        else appendLog(`第 ${message.index+1} 条指令完成`,'success');
        renderSteps(); renderProperties();
        if (message.state === 'running') document.querySelector('.step.running')?.scrollIntoView({block:'nearest'});
      } else if (event === 'variables') { liveValues = message.values; renderVariables(); }
      else if (event === 'log') appendLog(message.text);
      else if (['finished','failed','stopped'].includes(event)) {
        starting = false; pausedId = null; pauseId = null; pauseReason = ''; controlPending = null;
        if (event === 'failed' && message.id) states.set(message.id,'failed');
        const text = event === 'finished' ? '执行完成' : event === 'stopped' ? '已停止' : '执行失败：'+message.error;
        $('run-status').textContent = event === 'failed' ? '执行失败' : text;
        appendLog(text,event === 'failed' ? 'error' : 'success'); render();
      }
    }
  }
  function renderElements() {
    const box = $('element-list'); box.replaceChildren();
    if (!elements.length) box.append(node('span','hint','元素库为空，先抓取一个网页元素。'));
    for (const item of elements) {
      const button = node('button','element-item',item.name); button.append(node('small','',item.group));
      button.disabled = running || pending || controlPending !== null || invalid;
      button.onclick = () => {
        const step = flow?.steps.find(s => s.id === selected);
        if (!step || !Object.hasOwn(step.params,'element')) return notify('先选择一条点击、输入、获取文本或等待网页元素指令。');
        edit(next => { const params = next.steps.find(s => s.id === selected).params; params.element = item.name; params.group = item.group; params.xpath = ''; });
      };
      box.append(button);
    }
  }
  document.querySelectorAll('[data-action]').forEach(button => button.onclick = () => {
    const action = button.dataset.action;
    if (['up','down','duplicate','delete'].includes(action)) edit(next => {
      const index = next.steps.findIndex(s => s.id === selected); if (index < 0) return;
      if (action === 'delete') next.steps.splice(index,1);
      else if (action === 'duplicate') { const copy = structuredClone(next.steps[index]); copy.id = crypto.randomUUID(); next.steps.splice(index+1,0,copy); selected = copy.id; }
      else { const dest = index+(action === 'up' ? -1 : 1); if (dest >= 0 && dest < next.steps.length) [next.steps[index],next.steps[dest]] = [next.steps[dest],next.steps[index]]; }
    });
    else requestAction(action);
  });
  $('search').oninput = renderCatalog;
  $('flow-name').onchange = () => edit(next => { next.name = $('flow-name').value; });
  $('drop-end').ondragover = e => e.preventDefault();
  $('drop-end').ondrop = e => drop(e,null);
  $('drop-end').onclick = () => { $('search').focus(); };
  $('add-variable').onclick = () => edit(next => {
    let n = 1; while (Object.hasOwn(next.variables,'variable_'+n)) n++;
    next.variables['variable_'+n] = '';
  });
  $('load-elements').onclick = () => send({type:'elements'});
  $('clear-logs').onclick = () => { logCount = 0; $('logs').replaceChildren(); $('log-count').textContent = '0'; };
  document.querySelectorAll('[data-tab]').forEach(button => button.onclick = () => showTab(button.dataset.tab));
  document.addEventListener('keydown',event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); document.activeElement?.blur(); requestAction('save'); }
  });
  window.addEventListener('message',event => receive(event.data || {}));
  send({type:'ready'});
  if (!vscode) notify('界面预览模式：可编辑并下载流程；实际运行请使用 VS Code 中的 WBot Studio。');
})();
