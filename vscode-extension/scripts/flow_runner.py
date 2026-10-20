"""解释执行 wbot-flow JSON，输出逐步事件；不生成或求值 Python 代码。"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
FIELDS = {
    'web.connect': [], 'web.click': ['element', 'group', 'xpath'],
    'web.input': ['element', 'group', 'xpath', 'text'],
    'web.text': ['element', 'group', 'xpath', 'output'],
    'web.wait': ['element', 'group', 'xpath'],
    'set': ['output', 'value'], 'replace': ['text', 'old', 'new', 'output'],
    'log': ['text'], 'wait': ['seconds'], 'file.read': ['path', 'output'],
    'file.write': ['path', 'text']
}
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def validate(flow):
    if not isinstance(flow, dict) or flow.get('format') != 'wbot-flow' or flow.get('version') != 1:
        raise ValueError('流程格式或版本无效')
    if not isinstance(flow.get('name'), str) or not 1 <= len(flow['name'].strip()) <= 200:
        raise ValueError('流程名称无效')
    variables = flow.get('variables')
    if not isinstance(variables, dict) or len(variables) > 200 or any(
            not NAME.fullmatch(k) or not isinstance(v, str) or len(v) > 100000 for k, v in variables.items()):
        raise ValueError('变量名称或内容无效')
    steps = flow.get('steps')
    if not isinstance(steps, list) or len(steps) > 1000:
        raise ValueError('指令数量无效')
    ids = set()
    for step in steps:
        if not isinstance(step, dict) or step.get('type') not in FIELDS:
            raise ValueError('未知指令')
        key = step.get('id')
        if not isinstance(key, str) or not key or key in ids:
            raise ValueError('指令 ID 无效')
        ids.add(key)
        if type(step.get('enabled')) is not bool or not isinstance(step.get('label'), str):
            raise ValueError('指令属性无效')
        if 'breakpoint' in step and type(step['breakpoint']) is not bool:
            raise ValueError('断点必须是布尔值')
        params = step.get('params')
        if not isinstance(params, dict):
            raise ValueError('参数无效')
        for name in FIELDS[step['type']]:
            value = params.get(name)
            if name == 'seconds':
                if type(value) not in (int, float) or not 0 <= value <= 3600:
                    raise ValueError('等待秒数必须在 0～3600 之间')
            elif not isinstance(value, str) or len(value) > 100000:
                raise ValueError('参数必须是文本：'+name)
        if 'output' in params and not NAME.fullmatch(params['output']):
            raise ValueError('输出变量名称无效')
        if step['enabled'] and step['type'] in ('web.click', 'web.input', 'web.text', 'web.wait'):
            if not params['element'].strip() and not params['xpath'].strip():
                raise ValueError('网页操作必须选择元素或填写 XPath')
    return flow


def emit(event, **data):
    print(json.dumps(dict(event=event, **data), ensure_ascii=False), flush=True)


class DebugController:
    """仅在指令执行前暂停；恢复时不重复检查当前指令的断点。"""

    def __init__(self, cancelled, debug=False):
        self.cancelled = cancelled
        self.debug = debug
        self._condition = threading.Condition()
        self._entry = debug
        self._pause_requested = False
        self._single_step = False
        self._paused = False
        self._resume_mode = None
        self._pause_id = 0

    def command(self, command):
        fields = command.split()
        if not fields:
            return
        with self._condition:
            if fields == ['stop']:
                self.cancelled.set()
                self._condition.notify_all()
            elif fields == ['pause'] and not self._paused:
                self._pause_requested = True
            elif (len(fields) == 2 and fields[0] in ('resume', 'step') and self._paused
                  and fields[1] == str(self._pause_id)):
                # 接受后立即清除暂停状态，重复点击不会累计待执行步数。
                # 暂停编号阻止延迟到达的旧命令越过后续断点。
                self._paused = False
                self._single_step = fields[0] == 'step'
                self._resume_mode = fields[0]
                self._condition.notify_all()

    def before_step(self, item, index, send):
        with self._condition:
            if self.cancelled.is_set():
                return False
            reason = None
            if self._entry:
                reason = 'entry'
            elif self._pause_requested:
                reason = 'pause'
            elif self._single_step:
                reason = 'step'
            elif self.debug and item.get('breakpoint', False):
                reason = 'breakpoint'
            self._entry = False
            if reason is None:
                return True
            self._pause_requested = False
            self._single_step = False
            self._paused = True
            self._resume_mode = None
            self._pause_id += 1
            send('paused', id=item['id'], index=index, reason=reason, pauseId=self._pause_id)
            while self._paused and not self.cancelled.is_set():
                # 兼容直接调用 execute 的调用方自行设置 cancelled。
                self._condition.wait(0.1)
            if self.cancelled.is_set():
                return False
            send('continued', id=item['id'], index=index, mode=self._resume_mode, pauseId=self._pause_id)
            return True


def execute(flow, workspace, cancelled, send=emit, debugger=None):
    validate(flow)
    values = dict(flow['variables'])
    root = Path(workspace).resolve()
    browser = None

    def expand(text):
        def lookup(match):
            name = match.group(1)
            if name not in values:
                raise ValueError('变量尚未定义：'+name)
            return values[name]
        result = re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', lookup, text)
        if len(result) > 1000000:
            raise ValueError('展开后的文本超过 1 MB')
        return result

    def local_path(text):
        target = (root / expand(text)).resolve()
        if not target.is_relative_to(root) or target == root:
            raise ValueError('文件路径必须位于当前工作区内')
        return target

    current = None
    try:
        send('started', total=sum(s['enabled'] for s in flow['steps']))
        send('variables', values=values)
        for index, item in enumerate(flow['steps']):
            if cancelled.is_set():
                send('stopped')
                return 130
            if not item['enabled']:
                continue
            current = item['id']
            if debugger is not None and not debugger.before_step(item, index, send):
                send('stopped')
                return 130
            if cancelled.is_set():
                send('stopped')
                return 130
            send('step', id=current, index=index, state='running')
            kind, p = item['type'], item['params']
            if kind == 'set':
                values[p['output']] = expand(p['value'])
            elif kind == 'replace':
                text, old, new = expand(p['text']), expand(p['old']), expand(p['new'])
                count = text.count(old)
                if len(text) + count * (len(new) - len(old)) > 1000000:
                    raise ValueError('替换后的文本超过 1 MB')
                values[p['output']] = text.replace(old, new)
            elif kind == 'log':
                send('log', text=expand(p['text']))
            elif kind == 'wait':
                if cancelled.wait(p['seconds']):
                    send('stopped')
                    return 130
            elif kind == 'file.read':
                with local_path(p['path']).open('r', encoding='utf-8-sig') as stream:
                    text = stream.read(1000001)
                if len(text) > 1000000:
                    raise ValueError('读取文件超过 1 MB')
                values[p['output']] = text
            elif kind == 'file.write':
                target = local_path(p['path'])
                text = expand(p['text'])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding='utf-8')
            elif kind == 'web.connect':
                from wbot import web
                browser = web.get(base_url=os.environ.get('WBOT_BRIDGE_URL', 'http://127.0.0.1:8790'))
            else:
                if browser is None:
                    raise ValueError('请在网页指令前添加「连接已抓取网页」')
                if p['element'].strip():
                    from wbot.selector import SelectorStore
                    target = SelectorStore().get(expand(p['element']), group=expand(p['group']))
                else:
                    target = expand(p['xpath'])
                element = browser.find(target, timeout=30 if kind == 'web.wait' else 10)
                if kind == 'web.click':
                    element.click()
                elif kind == 'web.input':
                    element.input(expand(p['text']))
                elif kind == 'web.text':
                    values[p['output']] = str(element.get_text())
            if cancelled.is_set():
                send('stopped')
                return 130
            send('step', id=current, index=index, state='done')
            send('variables', values={k: v[:4000] for k, v in values.items()})
        send('finished')
        return 0
    except Exception as exc:
        send('failed', id=current, error=str(exc))
        return 1


def watch_commands(remaining, debugger):
    """首行是流程 JSON，其余各行是控制命令；父进程断开也停止执行。"""
    pending = remaining
    try:
        while not debugger.cancelled.is_set():
            while b'\n' in pending:
                raw, pending = pending.split(b'\n', 1)
                debugger.command(raw.decode('ascii', errors='replace').strip())
                if debugger.cancelled.is_set():
                    return
            if len(pending) > 1024:
                debugger.command('stop')
                return
            chunk = os.read(0, 4096)
            if not chunk:
                debugger.command('stop')
                return
            pending += chunk
    except OSError:
        debugger.command('stop')


def main():
    parser = argparse.ArgumentParser(description='执行 WBot 可视化流程')
    parser.add_argument('--debug', action='store_true', help='入口暂停并启用断点')
    args = parser.parse_args()
    try:
        raw = b''
        while b'\n' not in raw:
            chunk = os.read(0, 4096)
            if not chunk:
                raise ValueError('未收到流程数据')
            raw += chunk
            if len(raw) > 2000000:
                raise ValueError('流程文件过大')
        first, remaining = raw.split(b'\n', 1)
        flow = validate(json.loads(first.decode('utf-8')))
    except Exception as exc:
        emit('failed', error=str(exc))
        return 1
    cancelled = threading.Event()
    debugger = DebugController(cancelled, debug=args.debug)
    threading.Thread(target=watch_commands, args=(remaining, debugger), daemon=True).start()
    return execute(flow, os.getcwd(), cancelled, debugger=debugger)


if __name__ == '__main__':
    raise SystemExit(main())
