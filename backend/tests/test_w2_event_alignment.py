"""
W2-1 测试: 端到端 ASGI 收集 use_langchain=true 全部 SSE 事件
"""

import json
import pytest
import httpx
from httpx import ASGITransport
from app.main import app


async def _collect_sse_events(message: str, session_id: str = "", use_langchain=True):
    """跑一遍 /api/chat/stream, 收集所有 SSE 事件 data"""
    transport = ASGITransport(app=app)  # type: ignore
    events = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = {
            "message": message,
            "use_langchain": use_langchain,
            "session_id": session_id or f"w2-{hash(message) % 99999}",
        }
        async with client.stream("POST", "/api/chat/stream", json=body, timeout=httpx.Timeout(60.0)) as resp:
            if resp.status_code != 200:
                return events
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                    events.append(ev)
                except json.JSONDecodeError:
                    continue
    return events


@pytest.mark.asyncio
async def test_sse_event_types():
    """收集端到端 use_langchain=true 的所有 SSE event type"""
    events = await _collect_sse_events("用 terminal 工具查 date, 报时间")
    types = [e.get("type", "?") for e in events]
    from collections import Counter
    cnt = Counter(types)
    print(f"\n[SSE events] 总数={len(events)}, type 分布:")
    for t, n in cnt.most_common():
        print(f"  {t:25s} ×{n}")

    required = {"start", "done"}
    missing = required - set(types)
    assert not missing, f"缺核心: {missing}"


@pytest.mark.asyncio
async def test_sse_vs_stream_py_11():
    """跟 stream.py 11 类对齐"""
    STREAM_PY_EVENTS = {
        "start", "done", "error",
        "progress", "content",
        "thinking_delta", "thinking_done",
        "tool_start", "tool_complete", "tool_error", "tool_feedback",
        "ask", "budget_warning", "usage", "context",
    }

    events = await _collect_sse_events("用 terminal 工具查 date 报时间")
    produced = {e.get("type", "?") for e in events}
    missing = STREAM_PY_EVENTS - produced
    extra = produced - STREAM_PY_EVENTS
    print(f"\n[对齐 SSE] produced={len(produced)}, missing={missing}, extra={extra}")
    assert {"start", "done"}.issubset(produced)
