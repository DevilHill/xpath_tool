"""核对 VSIX 中的可执行资源与源码逐字节一致。"""
from io import BytesIO
from pathlib import Path
import json
import zipfile

extension = Path(__file__).resolve().parents[1]
root = extension.parent
package = root / 'dist/wbot-studio-0.3.0.vsix'
checked = 0
with zipfile.ZipFile(package) as archive:
    names = set(archive.namelist())
    assert not any('/node_modules/' in name or '/test/' in name or name.endswith('.sqlite3') for name in names)
    manifest = json.loads(archive.read('extension/package.json'))
    assert manifest['capabilities']['untrustedWorkspaces']['supported'] is False
    assert len(manifest['contributes']['commands']) == 24
    for name in names:
        if not name.startswith('extension/') or name.endswith('/'):
            continue
        relative = name.removeprefix('extension/')
        source = extension / relative
        if relative == 'LICENSE.txt':
            source = root / 'LICENSE'
        elif relative.lower() == 'readme.md':
            source = extension / 'README.md'
        elif relative.startswith('runtime/'):
            inside = relative.removeprefix('runtime/')
            if inside.startswith(('app/', 'wbot/', 'extension/')):
                source = root / inside
            elif inside in ('bridge_server.py', 'flow_runner.py'):
                source = extension / 'scripts' / inside
        assert source.is_file(), source
        assert archive.read(name) == source.read_bytes(), name
        checked += 1
    wheel = zipfile.ZipFile(BytesIO(archive.read('extension/runtime/wheels/wbot-0.1.0-py3-none-any.whl')))
    wheel_count = 0
    for name in wheel.namelist():
        if name.startswith('wbot/') and name.endswith('.py'):
            assert wheel.read(name) == (root / name).read_bytes(), name
            wheel_count += 1
print(f'VSIX 资源逐字节一致：{checked} 个文件；内置 wheel：{wheel_count} 个 Python 文件。')
