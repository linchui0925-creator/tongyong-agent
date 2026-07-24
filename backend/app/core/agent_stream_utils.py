"""Helpers for the Agent streaming loop.

Keeping these helpers separate makes `agent.py` easier to read and test,
while preserving the existing stream behavior.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncGenerator, Dict, Iterable, List, Tuple

from app.tools.registry import registry as _tool_registry


def response_usage_dict(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if hasattr(response, "usage_legacy"):
        return response.usage_legacy
    if isinstance(usage, dict):
        return {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    return {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }


def iter_thinking_text(response: Any) -> Iterable[str]:
    for chunk in getattr(response, "thinking", []) or []:
        text = getattr(chunk, "text", chunk)
        if isinstance(text, str):
            yield text
        else:
            yield str(text)

MUST_USE_TOOL_TRIGGERS: Tuple[str, ...] = (
    "请使用", "务必调用", "必须调用", "用工具", "调用工具",
    "打开网页", "访问", "截图", "读取文件",
    "playwright", "browser", "read_file", "search_files", "terminal",
    "use the tool", "call the tool", "must call", "must use",
)
VISIBLE_CHROME_TRIGGERS: Tuple[str, ...] = (
    "可视化", "可见窗口", "可见浏览器", "真实浏览器", "本地chrome",
    "本地 chrome", "google浏览器", "google chrome", "chrome浏览器",
    "用我的浏览器", "用我的 chrome", "在 chrome 里", "在浏览器里",
)


def message_requires_tool_call(user_text: str) -> bool:
    text = (user_text or "").casefold()
    return any(token in text for token in MUST_USE_TOOL_TRIGGERS)


def message_requires_visible_chrome(user_text: str) -> bool:
    text = (user_text or "").casefold()
    return any(token in text for token in VISIBLE_CHROME_TRIGGERS)


def has_cdp_url(user_text: str) -> bool:
    text = user_text or ""
    return "ws://" in text and ("/json" in text or "/devtools/page/" in text)


def clean_thinking(text: str) -> tuple[str, str]:
    match = re.search(r"<think>([\s\S]*?)</think>", text)
    if match:
        thinking = match.group(1)
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, count=1).strip()
        return cleaned, thinking
    return text, ""


def format_tool_result_text(
    name: str,
    success: bool,
    result: str,
    error_msg: str = "",
    error_type: str = "",
    suggestion: str = "",
    tool_call_id: str = "",
    elapsed: float = 0.0,
) -> str:
    emoji = _tool_registry.get_emoji(name)
    result_clean = (result or "").strip()
    if success:
        preview = result_clean[:500]
        if len(result_clean) > 500:
            preview += "\n...[结果已截断]"
        content = f"[{emoji} {name}] 执行成功:\n{preview}"
    else:
        lines = [f"[{emoji} {name}] 执行失败: {error_msg}"]
        if error_type:
            lines.append(f"错误类型: {error_type}")
        if suggestion:
            lines.append(f"建议: {suggestion}")
        content = "\n".join(lines)
    import json as _json
    payload = {
        "tool_call_id": tool_call_id,
        "tool_name": name,
        "emoji": emoji,
        "success": success,
        "content": content,
        "result_full": result_clean,
        "error": error_msg if not success else "",
        "error_type": error_type if not success else "",
        "suggestion": suggestion if not success else "",
        "elapsed": round(float(elapsed or 0.0), 4),
    }
    return _json.dumps(payload, ensure_ascii=False)


async def with_heartbeat(awaitable, label: str, interval: float = 10.0):
    task = asyncio.ensure_future(awaitable)
    import time as _time
    t0 = _time.time()
    try:
        while not task.done():
            await asyncio.sleep(interval)
            if not task.done():
                elapsed = _time.time() - t0
                yield ("heartbeat", f"{label} ({elapsed:.0f}s)")
        result = task.result()
        yield ("done", result)
    except asyncio.CancelledError:
        task.cancel()
        raise
