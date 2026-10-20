// Playwright CLI: run-code --filename vscode-extension/test/browser-ui.js
async (page) => {
  await page.addInitScript(() => {
    window.__sent = [];
    window.acquireVsCodeApi = () => ({postMessage: message => window.__sent.push(message)});
  });
  await page.reload();
  const result = await page.evaluate(() => {
    const flow = FlowModel.sample();
    const emit = data => window.dispatchEvent(new MessageEvent('message',{data}));
    emit({type:'document',flow,version:1,dirty:false});
    const input = document.getElementById('param-text');
    input.value = '保存新内容';
    input.dispatchEvent(new Event('change'));
    document.querySelector('[data-action=save]').click();
    const before = __sent.map(message => message.type);
    const edited = __sent.find(message => message.type === 'edit').flow;
    emit({type:'document',flow:edited,version:2,dirty:true});
    const after = __sent.map(message => message.type);
    emit({type:'runState',running:true});
    emit({type:'invalid',error:'测试格式错误'});
    const stopEnabled = !document.getElementById('stop').disabled;
    emit({type:'event',event:'step',id:flow.steps[0].id,state:'running',index:0});
    emit({type:'runState',running:false});
    emit({type:'document',flow,version:3,dirty:false});
    return {before,after,stopEnabled,recovered:document.querySelectorAll('.step').length,
      runEnabled:!document.getElementById('run').disabled};
  });
  if (result.before.includes('save') || !result.after.includes('save') || !result.stopEnabled ||
      result.recovered !== 3 || !result.runEnabled) throw new Error(JSON.stringify(result));
  console.log(JSON.stringify(result));
}
