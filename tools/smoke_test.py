"""端到端冒烟测试：启动本地服务并依次调用所有 API。

用法：python tools/smoke_test.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.server import run_server  # noqa: E402

SAMPLE = """<!DOCTYPE html><html><body>
<header class="site-header">
  <button id="login-btn" class="btn btn-primary active" type="button">登录</button>
  <a href="/cart" class="cart-link">购物车 <span class="cart-badge">3</span></a>
</header>
<section class="product-list">
  <article class="product-card" data-sku="A1001"><h3>无线降噪耳机 Pro</h3><button class="add-to-cart" data-sku="A1001">加入购物车</button></article>
  <article class="product-card" data-sku="A1002"><h3>智能手表 S8</h3><button class="add-to-cart" data-sku="A1002">加入购物车</button></article>
</section>
<form id="login-form" class="login-box"><input id="username" name="username" placeholder="请输入用户名"><button type="submit">登 录</button></form>
</body></html>"""


def call(port: int, path: str, payload: dict | None = None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    httpd, port = run_server(0)
    print(f"服务已启动，端口 {port}\n")
    ok = True

    try:
        # 静态资源
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            html = r.read().decode("utf-8")
        print(f"[1] GET /            -> {r.status}, {len(html)} 字节, 含标题: {'XPath Studio' in html}")

        # parse
        res = call(port, "/api/parse", {"html": SAMPLE})
        token = res["token"]
        print(f"[2] /api/parse       -> 节点 {res['count']}, top={res['desc']['top'][:3]}")

        # 从树里找到登录按钮的 idx
        def find_idx(node, pred):
            if pred(node):
                return node["idx"]
            for c in node.get("children", []):
                r = find_idx(c, pred)
                if r is not None:
                    return r
            return None

        btn_idx = find_idx(res["tree"], lambda n: n["attrs"].get("id") == "login-btn")

        # validate —— 同时校验匹配节点的 idx 是否正确（验证 id() 稳定性修复）
        v = call(port, "/api/validate", {"token": token, "xpath": "//button[@id='login-btn']"})
        got = v["matches"][0]["idx"] if v["matches"] else None
        print(f"[3] /api/validate    -> valid={v['valid']} count={v['count']} idx={got} (期望 {btn_idx})")
        assert v["count"] == 1
        assert got == btn_idx, "匹配节点的 idx 映射错误（id() 稳定性问题）"

        v2 = call(port, "/api/validate", {"token": token, "xpath": "//div[@@bad"})
        print(f"    /api/validate 非法 -> valid={v2['valid']} error={v2['error'][:40]}")
        assert not v2["valid"]

        # gen
        g = call(port, "/api/gen", {"token": token, "idx": btn_idx})
        print(f"[4] /api/gen         -> idx={btn_idx} best={g['best']}")
        print(f"    候选 {len(g['xpath'])} 条, CSS={g['css']['css']}, Playwright={len(g['playwright'])} 条")
        assert g["best"] and g["xpath"]
        assert g["best"] == "//button[@id='login-btn']", f"最短唯一 XPath 异常: {g['best']}"

        # nl
        nl = call(port, "/api/nl", {"token": token, "query": "登录按钮"})
        print(f"[5] /api/nl          -> 命中 {nl['count']} 条, 首条={nl['matches'][0]['tag'] if nl['matches'] else '-'}")

        # scan
        sc = call(port, "/api/scan", {"token": token})
        print(f"[6] /api/scan        -> 可交互元素 {sc['count']} 个")
        for it in sc["items"][:3]:
            print(f"      [{it['level']} {it['score']}] {it['xpath']}")
        assert sc["count"] > 0

        # verify
        vb = call(port, "/api/verify", {"token": token, "selectors": [
            "//button[@id='login-btn']", ".add-to-cart", "//div[@id='nope']", "getByRole('button')", "//input[@name='username']",
        ]})
        print(f"[7] /api/verify      -> {vb['count']} 条")
        for r in vb["results"]:
            print(f"      {r['type']:10s} valid={r['valid']} count={r['count']} {r['selector']}")

        # ai test（无 key，应返回可读错误）
        ai = call(port, "/api/ai/test", {"config": {"baseUrl": "http://127.0.0.1:1", "apiKey": "x", "model": "y"}})
        print(f"[8] /api/ai/test     -> ok={ai['ok']} error={(ai.get('error') or '')[:50]}")

        print("\n全部接口调用完成 ✅")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"\n测试失败 ❌ {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
    finally:
        httpd.shutdown()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
