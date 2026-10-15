"""用本机 VS Code 运行隔离的扩展宿主测试，不修改日常 VS Code 配置。"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--code', required=True, help='VS Code 可执行文件的绝对路径')
parser.add_argument('--python', default=sys.executable, help='已安装 wbot 与 lxml 的解释器')
args = parser.parse_args()
extension = Path(__file__).resolve().parents[1]
test_root = extension.parent / 'build' / 'vscode-tests'
test_root.mkdir(parents=True, exist_ok=True)
run_dir = Path(tempfile.mkdtemp(prefix='run-', dir=test_root))
workspace = run_dir / 'workspace'
workspace.mkdir()
env = dict(os.environ, WBOT_TEST_PYTHON=str(Path(args.python).resolve()))
env.pop('ELECTRON_RUN_AS_NODE', None)
env.pop('VSCODE_IPC_HOOK_CLI', None)
command = [args.code, '--disable-gpu', '--disable-updates',
           '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes',
           '--disable-extensions', '--no-proxy-server',
           f'--user-data-dir={run_dir / "user-data"}',
           f'--extensions-dir={run_dir / "extensions"}',
           f'--extensionDevelopmentPath={extension}',
           f'--extensionTestsPath={extension / "test/integration.js"}', str(workspace)]
print(f'测试目录：{run_dir}', flush=True)
with (run_dir / 'host.log').open('w', encoding='utf-8') as log:
    try:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        print('扩展宿主测试超时，请检查 host.log')
        raise SystemExit(1)
report = workspace / 'integration-report.json'
if report.exists():
    print(report.read_text(encoding='utf-8'))
else:
    print((run_dir / 'host.log').read_text(encoding='utf-8')[-8000:])
raise SystemExit(result.returncode if report.exists() else 1)
