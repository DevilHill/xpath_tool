(function (root, factory) {
  const value = factory();
  if (typeof module === 'object') module.exports = value;
  else root.FlowModel = value;
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';
  const field = (key, label, value = '', type = 'text') => ({key,label,value,type});
  const target = [field('element','元素库名称'),field('group','元素分组','默认'),field('xpath','或直接填写 XPath')];
  const catalog = [
    {type:'web.connect',name:'连接已抓取网页',group:'网页自动化',icon:'◎',description:'连接浏览器中最近一次抓取的页面。',fields:[]},
    {type:'web.click',name:'点击网页元素',group:'网页自动化',icon:'↗',description:'定位并点击元素；元素库名称与 XPath 任选其一。',fields:target},
    {type:'web.input',name:'填写输入框',group:'网页自动化',icon:'T',description:'向输入框填写文本，支持 ${变量名}。',fields:[...target,field('text','输入内容','','area')]},
    {type:'web.text',name:'获取元素文本',group:'网页自动化',icon:'≡',description:'读取元素文本并保存到变量。',fields:[...target,field('output','保存到变量','page_text')]},
    {type:'web.wait',name:'等待网页元素',group:'网页自动化',icon:'◷',description:'等待元素出现，最多等待 30 秒。',fields:target},
    {type:'set',name:'设置变量',group:'数据处理',icon:'x',description:'设置文本变量；可以引用已有变量。',fields:[field('output','变量名称','message'),field('value','变量值','你好，WBot！','area')]},
    {type:'replace',name:'替换文本',group:'数据处理',icon:'↔',description:'将文本中的所有匹配内容替换为新内容。',fields:[field('text','原始文本','${message}','area'),field('old','查找内容'),field('new','替换为'),field('output','保存到变量','result')]},
    {type:'log',name:'输出日志',group:'流程控制',icon:'≋',description:'将文本或变量值输出到运行日志。',fields:[field('text','日志内容','${message}','area')]},
    {type:'wait',name:'等待',group:'流程控制',icon:'◷',description:'等待指定秒数。停止运行可立即结束等待。',fields:[field('seconds','等待秒数',1,'number')]},
    {type:'file.read',name:'读取文本文件',group:'文件操作',icon:'▤',description:'读取工作区内的 UTF-8 文本文件。',fields:[field('path','工作区内相对路径','data.txt'),field('output','保存到变量','file_text')]},
    {type:'file.write',name:'写入文本文件',group:'文件操作',icon:'▣',description:'以 UTF-8 写入工作区内文件，覆盖原有内容。',fields:[field('path','工作区内相对路径','output/result.txt'),field('text','文件内容','${message}','area')]}
  ];
  const definition = type => catalog.find(item => item.type === type);
  const id = () => globalThis.crypto.randomUUID();
  function step(type) {
    const def = definition(type);
    if (!def) throw new Error('未知指令：'+type);
    return {id:id(),type,label:'',enabled:true,breakpoint:false,params:Object.fromEntries(def.fields.map(f => [f.key,f.value]))};
  }
  function sample() {
    return {format:'wbot-flow',version:1,name:'我的第一个自动化',variables:{message:'你好，WBot！'},
      steps:[step('log'),step('wait'),Object.assign(step('log'),{params:{text:'流程执行完成。'}})]};
  }
  function validate(flow) {
    if (!flow || flow.format !== 'wbot-flow' || flow.version !== 1) throw new Error('需要 wbot-flow 格式、版本 1 的流程文件');
    if (typeof flow.name !== 'string' || !flow.name.trim() || flow.name.length > 200) throw new Error('流程名称应为 1～200 个字符');
    if (!flow.variables || Array.isArray(flow.variables) || typeof flow.variables !== 'object') throw new Error('变量必须是对象');
    const entries = Object.entries(flow.variables);
    if (entries.length > 200 || entries.some(([key,value]) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) || typeof value !== 'string' || value.length > 100000)) throw new Error('最多 200 个文本变量；名称只能包含字母、数字、下划线，不能以数字开头');
    if (!Array.isArray(flow.steps) || flow.steps.length > 1000) throw new Error('最多支持 1000 条指令');
    const ids = new Set();
    for (const item of flow.steps) {
      const def = definition(item?.type);
      if (!def || typeof item.id !== 'string' || !item.id || ids.has(item.id)) throw new Error('指令类型无效或 ID 重复');
      ids.add(item.id);
      if (typeof item.enabled !== 'boolean' || typeof item.label !== 'string' || item.label.length > 200) throw new Error('指令标题或启用状态无效');
      if (item.breakpoint !== undefined && typeof item.breakpoint !== 'boolean') throw new Error('指令断点状态必须是布尔值');
      if (!item.params || typeof item.params !== 'object' || Array.isArray(item.params)) throw new Error('指令参数无效');
      for (const f of def.fields) {
        const value = item.params[f.key];
        if (f.type === 'number' ? typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 3600 : typeof value !== 'string' || value.length > 100000) throw new Error(`${def.name}：${f.label}格式无效`);
        if (f.key === 'output' && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(value)) throw new Error('输出变量名称无效');
      }
    }
    if (JSON.stringify(flow).length > 1000000) throw new Error('流程文件过大');
    return flow;
  }
  return {catalog,definition,step,sample,validate};
});
