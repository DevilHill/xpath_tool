"""重复目标在包装层变化后仍可定位；同时验证 Python/JS 候选与评分一致。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import xpath_engine as E

NODE = r"C:\Users\Azu19\.workbuddy-ai\binaries\node\versions\22.22.2-6\node.exe"
PROBE = r"""
const fs = require('fs');
const {JSDOM} = require('jsdom');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const dom = new JSDOM(data.html);
global.window = dom.window;
global.document = dom.window.document;
global.XPathResult = dom.window.XPathResult;
eval(fs.readFileSync('extension/lib/engine.js', 'utf8'));
const target = document.querySelector(data.target);
const engine = window.XPathStudioEngine;
const result = engine.genForElement(target);
const candidates = result.xpath.filter(c => c.strategy === 'ancestor');
const hit = data.previous ? engine.validate(data.previous) : null;
console.log(JSON.stringify({best:result.best, candidates:candidates,
 previousHit:hit ? hit.count === 1 && hit.matches[0].node === target : null}));
"""


def run(html: str, previous: str = ""):
    root, index, _tree, _count, elements = E.load(html)
    target = root.xpath("//section[1]//button")[0]
    result = E.gen_for_element(root, target, index)
    candidates = [c for c in result["xpath"] if c["strategy"] == "ancestor"]
    env = dict(os.environ, NODE_PATH=r"C:\Users\Azu19\.workbuddy-ai\binaries\node\workspace\node_modules")
    js = subprocess.run([NODE, "-e", PROBE], cwd=ROOT, env=env,
                        input=json.dumps({"html": html, "target": "section button", "previous": previous}),
                        text=True, encoding="utf-8", capture_output=True, timeout=30, check=True)
    parsed = json.loads(js.stdout)
    assert parsed["best"] == result["best"], (parsed["best"], result["best"])
    assert parsed["candidates"] == candidates, (parsed["candidates"], candidates)
    assert len(candidates) <= 4
    for c in candidates:
        assert E._locates_only(root, c["xpath"], target) and c["unique"] and c["count"] == 1
    if previous:
        assert E._locates_only(root, previous, target) and parsed["previousHit"]
    return result, candidates


HTML = '''<html><body>
<section data-testid="account-panel"><div><span><button name="save">保存</button></span></div></section>
<section data-testid="other-panel"><div><span><button name="save">保存</button></span></div></section>
</body></html>'''

result, candidates = run(HTML)
assert candidates and result["best"] == "//section[@data-testid='account-panel']//button[@name='save']"
print("[OK] 重复按钮通过稳定容器唯一定位，Python/JS 候选和评分一致")

changed = HTML.replace('<div><span><button', '<aside>提示</aside><article><div><div><button').replace(
    '</button></span></div>', '</button></div></div></article>')
run(changed, result["best"])
print("[OK] 插入兄弟节点并增删包装层后，原定位器仍唯一命中同一目标")

duplicate = HTML.replace('data-testid="other-panel"', 'data-testid="account-panel"')
assert not run(duplicate)[1]
print("[OK] 非唯一祖先属性不会被当作可靠锚点")

ambiguous = HTML.replace('</span>', '<button name="save">保存</button></span>')
assert not run(ambiguous)[1]
print("[OK] 容器内有相同按钮时，不产生伪唯一候选")

dynamic = HTML.replace('data-testid="account-panel"', 'id="j_idt88:panel"')
assert not run(dynamic)[1]
print("[OK] 动态祖先 ID 不用于稳定锚定")

quoted = HTML.replace('account-panel', 'account&apos;s&quot;panel')
assert run(quoted)[1]
print("[OK] 祖先属性包含单双引号时正确转义")

print("祖先锚定 6 个场景全部通过")
