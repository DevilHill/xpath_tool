"""AI 客户端：走 OpenAI 兼容的 /chat/completions 协议。

兼容 OpenAI、DeepSeek、通义千问(DashScope 兼容模式)、Moonshot、智谱、本地 Ollama 等。
只用标准库 urllib 发请求，避免额外依赖，方便打包。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

SYSTEM_PROMPT = """你是一名资深的 Web 自动化 / 爬虫工程师，精通 XPath。
用户会给你一段 HTML 源码和一个目标元素的自然语言描述，你要输出最稳健的 XPath 表达式。

要求：
1. 优先使用稳定的定位方式：id > data-testid/data-qa > name/aria-label > 唯一属性 > 文本 > class > 结构路径。
2. 避免使用易变的绝对路径和纯索引（除非别无选择）。
3. 若目标不唯一，必须给出能唯一定位的表达式（可加位置限定或组合条件）。
4. 只返回 JSON，不要输出任何解释性文字、不要用 markdown 代码块包裹。

返回 JSON 格式（严格遵守）：
{
  "xpath": "最终的 XPath 表达式",
  "explain": "一句话说明为什么这样定位",
  "alternatives": ["备选表达式1", "备选表达式2"]
}"""


class AIError(Exception):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    # 去掉可能的 markdown 代码块
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试抓取第一个 { ... } 片段
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise AIError("模型返回的内容不是合法 JSON：\n" + text[:500])


def chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: int = 90,
) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AIError("未配置 API Base URL")
    if base.endswith("/chat/completions"):
        url = base
    elif base.endswith("/v1"):
        url = base + "/chat/completions"
    else:
        url = base + "/v1/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "XPathStudio/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise AIError(f"接口返回 {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise AIError(f"无法连接接口：{exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001
        raise AIError(f"请求失败：{exc}") from exc

    try:
        obj = json.loads(body)
        return obj["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise AIError(f"解析响应失败：{body[:400]}") from exc


def _trim_html(html: str, limit: int = 18000) -> str:
    """裁剪 HTML，保留开头与目标可能出现的片段，控制 token。"""
    html = html or ""
    if len(html) <= limit:
        return html
    head = html[: int(limit * 0.6)]
    tail = html[-int(limit * 0.4):]
    return head + "\n\n<!-- ...中间内容已省略... -->\n\n" + tail


def generate_xpath(config: dict[str, Any], html: str, instruction: str) -> dict[str, Any]:
    base_url = config.get("baseUrl", "")
    api_key = config.get("apiKey", "")
    model = config.get("model", "")
    if not api_key:
        raise AIError("尚未配置 API Key，请点击右上角「AI 设置」填写")

    user_msg = (
        "目标元素描述：\n"
        f"{instruction}\n\n"
        "以下是页面 HTML 源码：\n"
        "```html\n"
        f"{_trim_html(html)}\n"
        "```\n\n"
        "请给出定位该元素的最稳健 XPath，并严格按要求返回 JSON。"
    )
    content = chat(
        base_url,
        api_key,
        model,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    parsed = _extract_json(content)
    return {
        "xpath": str(parsed.get("xpath", "")).strip(),
        "explain": str(parsed.get("explain", "")).strip(),
        "alternatives": [str(x) for x in parsed.get("alternatives", []) if str(x).strip()],
        "raw": content,
    }
