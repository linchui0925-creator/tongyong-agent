"""
回归基线测试（pytest fixture 版）— W1-2

从 q1_test.py / q3a_test.py 抽成 pytest 形式, 跑通下面这俩:
  - test_use_langchain_baseline_dialog
  - test_use_langchain_baseline_tool_call

跑法: pytest tests/test_regression_baseline.py -v -s
需要: backend/.venv 含 .env (MiniMax / DeepSeek 凭证)
"""
import asyncio
import os
import time
from pathlib import Path

import pytest
import httpx

BACKEND = Path(__file__).parent.parent
for line in (BACKEND / ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ─────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """FastAPI app — 避免每个 test 重新 import"""
    from app.main import app
    return app


@pytest.fixture(scope="module")
def event_collector():
    """收集 SSE events"""
    class Collector:
        def __init__(self):
            self.seen = {}
            self.first_content = []
            self.first_tool = None
            self.content = ""
            self.elapsed = 0.0
            self.error = None
    return Collector()


async def stream_and_collect(client, body, collector):
    """发 SSE 请求, 收 events"""
    t0 = time.time()
    async with client.stream("POST", "/api/chat/stream", json=body,
                             timeout=httpx.Timeout(60.0)) as resp:
        assert resp.status_code == 200, f"HTTP {resp.status_code}"
        async for line in resp.aiter_lines():
            if not line or not line.startswith("data: "):
                continue
            import json
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            ev_type = ev.get("type", "unknown")
            collector.seen[ev_type] = collector.seen.get(ev_type, 0) + 1
            if ev_type == "content":
                if len(collector.first_content) < 3:
                    collector.first_content.append(ev.get("content", "")[:80])
                collector.content += ev.get("content", "")
            if ev_type == "tool_start" and collector.first_tool is None:
                collector.first_tool = ev
            if ev_type == "error":
                collector.error = ev.get("content", ev)[:300]
    collector.elapsed = time.time() - t0


@pytest.mark.asyncio
async def test_use_langchain_baseline_dialog(app, event_collector):
    """对比 baseline (use_langchain=false) vs use_langchain=true — 纯对话"""
    body = {
        "session_id": None,
        "message": "你好，1+1等于几？只回数字",
        "use_memory": False,
        "use_langchain": False,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await stream_and_collect(client, body, event_collector)

    # 答案含 "2"
    assert "2" in event_collector.content, f"baseline dialog missing '2': {event_collector.content!r}"
    # 至少有 start + content + done
    assert event_collector.seen.get("start", 0) >= 1
    assert event_collector.seen.get("content", 0) >= 1
    assert event_collector.seen.get("done", 0) == 1
    # 记录耗时 (用于 baseline 报告)
    print(f"\n[baseline dialog] elapsed={event_collector.elapsed:.1f}s, "
          f"events={event_collector.seen}")


@pytest.mark.asyncio
async def test_use_langchain_tool_call(app):
    """use_langchain=true 路径 + 工具调用 — 验 4 类核心 SSE 事件"""
    body = {
        "session_id": None,
        "message": "现在几点了？只调工具，不准自己编时间",
        "use_memory": False,
        "use_langchain": True,
    }
    transport = httpx.ASGITransport(app=app)
    seen = {}
    first_tool = None
    content = ""
    elapsed = 0.0
    t0 = time.time()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("POST", "/api/chat/stream", json=body,
                                 timeout=httpx.Timeout(60.0)) as resp:
            assert resp.status_code == 200, f"HTTP {resp.status_code}"
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                import json
                try:
                    ev = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                ev_type = ev.get("type", "unknown")
                seen[ev_type] = seen.get(ev_type, 0) + 1
                if ev_type == "content":
                    content += ev.get("content", "")
                if ev_type == "tool_start" and first_tool is None:
                    first_tool = ev
    elapsed = time.time() - t0

    # 1) 工具调用真发生了
    assert first_tool is not None, f"no tool_start event, seen={seen}"
    assert first_tool.get("tool_name") == "terminal", \
        f"expected terminal, got {first_tool.get('tool_name')!r}"
    assert "date" in str(first_tool.get("arguments", {})), \
        f"expected date command, args={first_tool.get('arguments')!r}"

    # 2) 5 类核心事件都在
    for t in ["start", "tool_start", "tool_complete", "content", "done"]:
        assert seen.get(t, 0) >= 1, f"missing {t} event, seen={seen}"

    # 3) 答案含时间 (年/月/日)
    import re
    assert re.search(r"\d{4}年\d{1,2}月", content) or re.search(r"2026", content), \
        f"answer should contain time, content={content!r}"

    print(f"\n[use_langchain tool_call] elapsed={elapsed:.1f}s, "
          f"events={seen}, first_tool={first_tool.get('tool_name')!r}")
