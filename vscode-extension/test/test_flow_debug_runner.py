"""通过真实子进程验证流程调试协议与执行副作用。"""
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'flow_runner.py'


def step(identifier, kind='set', *, enabled=True, breakpoint=None, **params):
    item = dict(id=identifier, type=kind, label='', enabled=enabled, params=params)
    if breakpoint is not None:
        item['breakpoint'] = breakpoint
    return item


def flow(*steps):
    return dict(format='wbot-flow', version=1, name='调试协议测试',
                variables={'initial': '初始值'}, steps=list(steps))


class Runner:
    def __init__(self, document, debug=True):
        self.directory = tempfile.TemporaryDirectory(prefix='wbot-debug-')
        self.root = Path(self.directory.name)
        self.events = []
        self.queue = queue.Queue()
        self.pause_id = None
        self.process = subprocess.Popen(
            [sys.executable, '-I', '-X', 'utf8', '-u', str(SCRIPT)] +
            (['--debug'] if debug else []),
            cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.process.stdin.write(json.dumps(document, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.queue.put(json.loads(line))
        except Exception as exc:
            self.queue.put(exc)
        finally:
            self.queue.put(None)

    def send(self, command):
        command = '\n'.join(f'{line} {self.pause_id}' if line in ('step', 'resume') else line
                            for line in command.split('\n'))
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()

    def next(self, event, timeout=5):
        deadline = time.monotonic() + timeout
        while True:
            try:
                value = self.queue.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise AssertionError(f'等待 {event} 超时；已收到：{self.events}') from exc
            if value is None:
                raise AssertionError(f'未收到 {event}，进程已退出；事件：{self.events}')
            if isinstance(value, Exception):
                raise value
            self.events.append(value)
            if value['event'] == event:
                if event == 'paused':
                    self.pause_id = value['pauseId']
                return value

    def finished(self, event='finished', code=0):
        result = self.next(event)
        actual = self.process.wait(timeout=5)
        if actual != code:
            raise AssertionError(f'退出码 {actual}，预期 {code}；{self.process.stderr.read()}')
        return result

    def close(self):
        if self.process.poll() is None:
            try:
                if not self.process.stdin.closed:
                    self.send('stop')
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            pipe.close()
        self.directory.cleanup()


class FlowDebugTests(unittest.TestCase):
    def runner(self, document, debug=True):
        runner = Runner(document, debug)
        self.addCleanup(runner.close)
        return runner

    def test_entry_breakpoint_step_variables_and_disabled_steps(self):
        runner = self.runner(flow(
            step('disabled-first', enabled=False, breakpoint=True, output='bad', value='bad'),
            step('first', output='value', value='第一步'),
            step('break', breakpoint=True, output='value', value='第二步'),
            step('disabled-middle', enabled=False, breakpoint=True, output='bad', value='bad'),
            step('last', 'file.write', path='result.txt', text='${value}')))
        paused = runner.next('paused')
        self.assertEqual((paused['id'], paused['index'], paused['reason']), ('first', 1, 'entry'))
        self.assertEqual(runner.events[-2]['event'], 'variables')
        self.assertEqual(runner.events[-2]['values'], {'initial': '初始值'})
        self.assertFalse(any(e['event'] == 'step' for e in runner.events))
        runner.send('resume')
        self.assertEqual(runner.next('continued')['mode'], 'resume')
        paused = runner.next('paused')
        self.assertEqual((paused['id'], paused['index'], paused['reason']), ('break', 2, 'breakpoint'))
        self.assertEqual(runner.events[-2]['values']['value'], '第一步')
        runner.send('step')
        self.assertEqual(runner.next('continued')['mode'], 'step')
        paused = runner.next('paused')
        self.assertEqual((paused['id'], paused['index'], paused['reason']), ('last', 4, 'step'))
        self.assertEqual(runner.events[-2]['values']['value'], '第二步')
        self.assertFalse((runner.root / 'result.txt').exists())
        runner.send('step')
        runner.finished()
        self.assertEqual((runner.root / 'result.txt').read_text(encoding='utf-8'), '第二步')
        self.assertEqual([e['id'] for e in runner.events
                          if e['event'] == 'step' and e['state'] == 'done'],
                         ['first', 'break', 'last'])
        self.assertEqual([e['pauseId'] for e in runner.events if e['event'] == 'paused'], [1, 2, 3])

    def test_normal_run_ignores_breakpoints_and_accepts_legacy_steps(self):
        runner = self.runner(flow(
            step('legacy', output='value', value='正常'),
            step('break', 'log', breakpoint=True, text='${value}')), debug=False)
        runner.finished()
        self.assertFalse(any(e['event'] in ('paused', 'continued') for e in runner.events))
        self.assertEqual([e['text'] for e in runner.events if e['event'] == 'log'], ['正常'])

    def test_manual_pause_in_normal_run_then_step(self):
        runner = self.runner(flow(
            step('wait', 'wait', seconds=0.3),
            step('set', output='value', value='已完成'),
            step('write', 'file.write', path='result.txt', text='${value}')), debug=False)
        self.assertEqual(runner.next('step')['id'], 'wait')
        runner.send('pause')
        paused = runner.next('paused')
        self.assertEqual((paused['id'], paused['reason']), ('set', 'pause'))
        self.assertEqual([e['id'] for e in runner.events
                          if e['event'] == 'step' and e['state'] == 'done'], ['wait'])
        runner.send('step')
        paused = runner.next('paused')
        self.assertEqual((paused['id'], paused['reason']), ('write', 'step'))
        self.assertEqual(runner.events[-2]['values']['value'], '已完成')
        runner.send('resume')
        runner.finished()
        self.assertEqual((runner.root / 'result.txt').read_text(encoding='utf-8'), '已完成')

    def test_stop_while_paused_has_no_side_effects(self):
        runner = self.runner(flow(step('write', 'file.write', path='result.txt', text='不应写入')))
        runner.next('paused')
        runner.send('stop')
        runner.finished('stopped', 130)
        self.assertFalse((runner.root / 'result.txt').exists())
        self.assertFalse(any(e['event'] == 'step' for e in runner.events))

    def test_eof_while_paused_stops(self):
        runner = self.runner(flow(step('write', 'file.write', path='result.txt', text='不应写入')))
        runner.next('paused')
        runner.process.stdin.close()
        runner.finished('stopped', 130)
        self.assertFalse((runner.root / 'result.txt').exists())

    def test_duplicate_resume_commands_do_not_accumulate(self):
        runner = self.runner(flow(
            step('wait', 'wait', seconds=0.2),
            step('set', output='value', value='不应提前执行'),
            step('write', 'file.write', path='result.txt', text='${value}')))
        runner.next('paused')
        runner.send('step\nstep\nresume')
        paused = runner.next('paused')
        self.assertEqual((paused['id'], paused['reason']), ('set', 'step'))
        self.assertEqual([e['id'] for e in runner.events
                          if e['event'] == 'step' and e['state'] == 'done'], ['wait'])
        self.assertNotIn('value', runner.events[-2]['values'])
        runner.send('resume')
        runner.finished()

    def test_pause_requested_during_last_step_does_not_prevent_completion(self):
        runner = self.runner(flow(step('wait', 'wait', seconds=0.2)), debug=False)
        runner.next('step')
        runner.send('pause')
        runner.finished()
        self.assertFalse(any(e['event'] == 'paused' for e in runner.events))

    def test_stale_pause_id_cannot_advance_new_pause(self):
        runner = self.runner(flow(
            step('first', output='x', value='x'),
            step('write', 'file.write', breakpoint=True, path='result.txt', text='${x}')))
        old_pause = runner.next('paused')['pauseId']
        runner.send('step')
        new_pause = runner.next('paused')['pauseId']
        self.assertNotEqual(old_pause, new_pause)
        runner.send(f'resume {old_pause}\nstep {old_pause}\nresume invalid\nstep invalid')
        runner.process.stdin.write('resume\nstep\n')
        runner.process.stdin.flush()
        with self.assertRaises(queue.Empty):
            runner.queue.get(timeout=0.2)
        self.assertIsNone(runner.process.poll())
        self.assertFalse((runner.root / 'result.txt').exists())
        runner.send('resume')
        runner.finished()
        self.assertEqual((runner.root / 'result.txt').read_text(encoding='utf-8'), 'x')

    def test_all_disabled_flow_finishes_without_entry_pause(self):
        runner = self.runner(flow(step('disabled', enabled=False, breakpoint=True, output='x', value='x')))
        runner.finished()
        self.assertFalse(any(e['event'] in ('paused', 'step') for e in runner.events))

    def test_breakpoint_requires_bool_before_any_execution(self):
        for invalid in ('true', 1, None, [], {}):
            with self.subTest(invalid=invalid):
                invalid_step = step('invalid', output='x', value='x')
                invalid_step['breakpoint'] = invalid
                runner = self.runner(flow(
                    step('write', 'file.write', path='result.txt', text='不应写入'),
                    invalid_step))
                failure = runner.finished('failed', 1)
                self.assertIn('断点', failure['error'])
                self.assertFalse((runner.root / 'result.txt').exists())

    def test_execute_existing_signature_remains_compatible(self):
        spec = importlib.util.spec_from_file_location('flow_runner', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        events = []
        with tempfile.TemporaryDirectory(prefix='wbot-direct-') as workspace:
            result = module.execute(
                flow(step('legacy', 'log', text='兼容')), workspace,
                threading.Event(), lambda event, **data: events.append(dict(event=event, **data)))
        self.assertEqual(result, 0)
        self.assertEqual(events[-1]['event'], 'finished')
        self.assertEqual([e['text'] for e in events if e['event'] == 'log'], ['兼容'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
