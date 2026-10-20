// Playwright CLI: run-code --filename vscode-extension/test/browser-debug.js
// 此处仅模拟 VS Code 与 Webview 间的消息；真实 runner/扩展宿主由其他回归覆盖。
async (page) => {
  await page.addInitScript(() => {
    window.__sent = [];
    window.acquireVsCodeApi = () => ({postMessage: message => window.__sent.push(structuredClone(message))});
  });
  await page.reload();
  const result = await page.evaluate(() => {
    const checks = [];
    const $ = id => document.getElementById(id);
    const assert = (condition, message) => { if (!condition) throw new Error(message); };
    const check = (condition, message) => { assert(condition, message); checks.push(message); };
    const emit = data => window.dispatchEvent(new MessageEvent('message', {data}));
    const event = data => emit({type:'event', ...data});
    const sent = type => window.__sent.filter(message => message.type === type);
    const last = type => sent(type).at(-1);
    const button = (id, name) => document.querySelector(`.step[data-id="${id}"] .${name}`);
    const flow = FlowModel.sample();
    flow.variables = {message:'执行之前'};
    flow.steps[0] = {...FlowModel.step('set'), params:{output:'message', value:'执行之后'}};
    flow.steps[1].params.seconds = 0;
    const [first, second, third] = flow.steps.map(item => item.id);
    let version = 1;
    const documentMessage = (value, dirty = true) => emit({type:'document', flow:value, version:version++, dirty});

    documentMessage(flow, false);
    check(!$('run').disabled && !$('debug').disabled && $('step').disabled && $('resume').disabled,
      '空闲状态提供普通运行与调试，禁用单步和继续');
    check($('run').title.includes('忽略断点') && $('step-count').title.includes('普通运行忽略断点'),
      '普通运行忽略断点的提示可见');
    check(button(second, 'breakpoint').getAttribute('aria-pressed') === 'false',
      '指令初始断点状态可被辅助技术读取');

    button(second, 'breakpoint').click();
    const edited = last('edit').flow;
    check(edited.steps[1].breakpoint === true && button(second, 'breakpoint').getAttribute('aria-pressed') === 'true',
      '断点切换写入流程文档，显示启用状态');
    const debugBefore = sent('debug').length;
    $('debug').click();
    check(sent('debug').length === debugBefore, '未确认的断点编辑先等待文档保存回执');
    documentMessage(edited);
    check(sent('debug').length === debugBefore + 1, '文档回执后发送调试命令');
    check($('debug').disabled && $('run').disabled && button(second, 'breakpoint').disabled,
      '调试启动消息尚未确认时禁止重复启动与断点编辑');
    documentMessage(edited, false);
    check(button(second, 'breakpoint').classList.contains('active') && $('saved-state').textContent.includes('已保存'),
      '保存后重读文档仍保留断点');

    emit({type:'runState', running:true, debugging:true, starting:true});
    check($('pause').disabled && $('step').disabled && $('resume').disabled &&
      !$('stop').disabled && $('debug-status').textContent.includes('准备'),
      '准备 Python 环境时不能暂停或推进，但可以停止启动');
    event({event:'started', total:3});
    check(!$('pause').disabled && !$('stop').disabled,
      'Python 启动事件解除准备状态，允许请求暂停');
    event({event:'variables', values:{message:'执行之前'}});
    event({event:'paused', id:first, index:0, reason:'entry', pauseId:101});
    check(document.querySelector('.step.paused')?.dataset.id === first &&
      document.querySelector('.step.paused .paused-label').textContent.includes('下一条执行') &&
      $('debug-status').textContent.includes('尚未执行'), '入口暂停标记准确显示下一条尚未执行的指令');
    check(!$('variables').hidden && $('variables-label').textContent.includes('暂停') &&
      document.querySelector('.variable-live').textContent === 'message = 执行之前' &&
      !document.querySelector('#variable-list input'), '暂停时自动显示只读的执行前变量值');
    check(!$('step').disabled && !$('resume').disabled && $('pause').disabled && !$('stop').disabled,
      '暂停时仅允许单步、继续或停止');
    const editsBefore = sent('edit').length;
    button(second, 'breakpoint').click();
    check(button(second, 'breakpoint').disabled && sent('edit').length === editsBefore,
      '暂停仍属于运行会话，不能修改断点');

    const stepBefore = sent('step').length;
    $('step').click();
    $('step').click();
    check(sent('step').length === stepBefore + 1 && last('step').pauseId === 101 &&
      $('step').disabled && $('resume').disabled, '单步携带当前暂停标识并立即禁用，防止连发');
    event({event:'continued'});
    check(!document.querySelector('.step.paused') && $('step').disabled && $('resume').disabled &&
      !$('pause').disabled, '收到继续事件后移除暂停标记，等待下一次暂停');
    event({event:'step', id:first, index:0, state:'running'});
    event({event:'step', id:first, index:0, state:'done'});
    event({event:'variables', values:{message:'执行之后'}});
    event({event:'paused', id:second, index:1, reason:'step', pauseId:102});
    check(document.querySelector('.step.paused')?.dataset.id === second &&
      document.querySelector(`.step[data-id="${first}"]`).classList.contains('done') &&
      $('debug-status').textContent.includes('单步') &&
      document.querySelector('.variable-live').textContent === 'message = 执行之后',
      '单步后暂停移至下一条指令，显示已更新变量与完成状态');
    check(!$('step').disabled && !$('resume').disabled, '新的暂停事件重新启用单步和继续');

    const resumeBefore = sent('resume').length;
    $('resume').click();
    $('resume').click();
    check(sent('resume').length === resumeBefore + 1 && last('resume').pauseId === 102 &&
      $('step').disabled && $('resume').disabled, '继续使用新的暂停标识并防止重复发送');
    event({event:'continued'});
    const pauseBefore = sent('pause').length;
    $('pause').click();
    $('pause').click();
    check(sent('pause').length === pauseBefore + 1 && $('pause').disabled &&
      $('debug-status').textContent.includes('当前指令完成后'), '手动暂停请求只发一次，并说明指令边界语义');
    event({event:'variables', values:{message:'执行之后'}});
    event({event:'paused', id:third, index:2, reason:'pause', pauseId:103});
    check($('debug-status').textContent.includes('手动暂停') && !$('step').disabled,
      '手动暂停回执恢复单步控制');

    // 错误回执应解除等待，仍只对当前暂停编号操作。
    $('step').click();
    emit({type:'error', error:'测试：控制请求未被接受'});
    check(!$('step').disabled && !$('resume').disabled &&
      $('notice').textContent.includes('控制请求未被接受'), '控制失败后恢复可重试状态并显示原因');
    const stopBefore = sent('stop').length;
    $('stop').click();
    $('stop').click();
    check(sent('stop').length === stopBefore + 1 && $('stop').disabled &&
      $('resume').disabled && $('step').disabled, '暂停状态可停止且不会重复发送停止请求');
    event({event:'paused', id:third, index:2, reason:'breakpoint', pauseId:104});
    check($('stop').disabled && $('resume').disabled && $('step').disabled && $('pause').disabled &&
      button(third, 'breakpoint').disabled && $('debug-status').textContent.includes('停止'),
      '停止在途收到迟到暂停事件，仍锁定调试和编辑按钮');
    event({event:'continued'});
    $('step').click();
    $('resume').click();
    $('pause').click();
    $('stop').click();
    check($('stop').disabled && $('resume').disabled && $('step').disabled && $('pause').disabled &&
      $('debug-status').textContent.includes('停止') && sent('stop').length === stopBefore + 1 &&
      sent('resume').length === resumeBefore + 1 && sent('pause').length === pauseBefore + 1,
      '停止在途收到迟到继续事件，也不会解锁或重复发送控制命令');
    event({event:'stopped'});
    emit({type:'runState', running:false, debugging:false});
    check(!$('run').disabled && !$('debug').disabled && !$('flow-name').disabled &&
      $('step').disabled && $('resume').disabled && $('pause').disabled && $('stop').disabled &&
      !button(second, 'breakpoint').disabled && !document.querySelector('.step.paused'),
      '停止后恢复普通编辑与运行按钮，清除暂停标记');

    $('run').click();
    check(last('run')?.type === 'run' && sent('debug').length === debugBefore + 1,
      '普通运行入口发送 run，与调试入口分开');
    emit({type:'runState', running:true, debugging:false});
    event({event:'started', total:3});
    check($('debug-status').textContent.includes('忽略断点') &&
      button(second, 'breakpoint').disabled, '普通运行时明确提示忽略断点，同时锁定文档');
    event({event:'finished'});
    emit({type:'runState', running:false, debugging:false});
    check(!$('run').disabled && $('debug-status').hidden, '正常完成后恢复就绪界面');

    $('debug').click();
    emit({type:'runState', running:true, debugging:true, starting:true});
    const startingStopBefore = sent('stop').length;
    $('stop').click();
    check(sent('stop').length === startingStopBefore + 1 && $('pause').disabled && $('stop').disabled,
      '准备 Python 期间可以发送停止，并保持停止等待状态');
    event({event:'started', total:3});
    check($('pause').disabled && $('step').disabled && $('resume').disabled && $('stop').disabled &&
      $('debug-status').textContent.includes('停止'),
      '启动取消在途的迟到 started 事件不会恢复控制按钮');
    event({event:'stopped'});
    emit({type:'runState', running:false, debugging:false, starting:false});
    check(!$('run').disabled && !$('debug').disabled && !$('flow-name').disabled,
      '取消准备完成后恢复编辑与重新启动');

    // 模拟已暂停会话在 Webview 重新创建后由宿主回放状态。
    documentMessage(edited, false);
    emit({type:'runState', running:true, debugging:true});
    event({event:'variables', values:{message:'恢复后的变量'}});
    event({event:'paused', id:second, index:1, reason:'breakpoint', pauseId:201});
    check(document.querySelector('.step.paused')?.dataset.id === second &&
      $('debug-status').textContent.includes('命中断点') &&
      document.querySelector('.variable-live').textContent.includes('恢复后的变量'),
      '宿主回放暂停与变量消息可恢复断点调试界面');
    $('resume').click();
    check(last('resume').pauseId === 201, '恢复后的继续命令使用回放的暂停标识');
    event({event:'stopped'});
    emit({type:'runState', running:false, debugging:false});
    return {passed:true, checks, count:checks.length};
  });
  console.log(JSON.stringify(result));
}
