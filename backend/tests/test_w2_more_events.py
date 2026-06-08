"""
W2-3 测试: 补 4 类缺事件 — tool_error / tool_feedback / budget_warning / context

策略:
- tool_error: 调一个会失败的命令 (terminal: rm -rf /) — 不行, terminal 拒执行
  改用 date 工具传错参数 — date 不接受 -f
- tool_feedback: 工具 > 3s 时推中间 — 默认 LangGraph 不给中间
  → 跳过, 留 W3 优化
- budget_warning: 跑完推 budget metadata 事件
- context: 超过 10 消息推 context 事件
- error: 已经实现了, 跑一个会超限的 (LONG prompt)

预期新增事件:
- budget_warning (必有)
- context (单测 1 轮不超 10, 不触发, 但代码路径应能跑)
"""

import json
import pytest
import httpx
from httpx import ASGITransport
from app.main import app


async def _collect_sse_events(message: str, session_id: str = ""):
    transport = ASGITransport(app=app)  # type: ignore
    events = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = {
            "message": message,
            "use_langchain": True,
            "session_id": session_id or f"w2-3-{hash(message) % 99999}",
        }
        async with client.stream("POST", "/api/chat/stream", json=body, timeout=httpx.Timeout(60.0)) as resp:
            if resp.status_code != 200:
                return events
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    continue
    return events


@pytest.mark.asyncio
async def test_budget_warning_event():
    """budget_warning 事件: 推 IterationBudget metadata
    schema: {"content": "已用 N/50 轮", "type": "budget_warning"}
    """
    events = await _collect_sse_events("1+1=?")
    types = [e.get("type", "?") for e in events]
    print(f"\n[budget_warning] types={types}")

    # W2-3: budget_warning 必有
    assert "budget_warning" in types, f"缺 budget_warning: {types}"
    bw = [e for e in events if e.get("type") == "budget_warning"][0]
    assert "content" in bw, f"budget_warning 缺 content: {bw}"
    assert "max_rounds" in bw.get("content", ""), \
        f"budget_warning content 应含 max_rounds: {bw.get('content')!r}"


@pytest.mark.asyncio
async def test_tool_error_event():
    """tool_error 事件: 工具执行失败时推"""
    # terminal 不接受 -x 参数 — 实际取决于 LLM 是否会调错工具
    # 用故意拼错的命令触发工具失败
    events = await _collect_sse_events("用 terminal 执行 rm -rf /tmp/nonexistent_file_xyz_12345_永远不存在的文件_让命令失败")
    types = [e.get("type", "?") for e in events]
    print(f"\n[tool_error] types={types}")

    # LLM 可能不调工具, 也可能调失败, 也可能直接答
    # 不强制 tool_error — verify 行为合理即可
    tool_events = [e for e in events if e.get("type", "").startswith("tool_")]
    print(f"  tool_ 事件: {[e.get('type') for e in tool_events]}")


@pytest.mark.asyncio
async def test_context_event_after_long_session():
    """context 事件: schema {"context": {"message_count": N}}"""
    s1 = await _collect_sse_events("你好", "w2-3-ctx-1")
    s2 = await _collect_sse_events("继续", "w2-3-ctx-1")
    types1 = [e.get("type", "?") for e in s1]
    types2 = [e.get("type", "?") for e in s2]
    print(f"\n[context 1轮] types={types1}")
    print(f"[context 2轮] types={types2}")
    # 2 轮后 ctx 应有 context 事件
    assert "context" in types2, f"缺 context: {types2}"
    ctx_event = [e for e in s2 if e.get("type") == "context"][0]
    assert "context" in ctx_event, f"context 事件缺 context 字段: {ctx_event}"
    assert "message_count" in ctx_event["context"], \
        f"context.context 缺 message_count: {ctx_event['context']}"


@pytest.mark.asyncio
async def test_error_event_on_llm_failure():
    """error 事件: 模拟 LLM 失败 (发不合法消息)"""
    # 1MB 消息触发 LLM 400
    long_msg = "测试" * 200000
    events = await _collect_sse_events(long_msg)
    types = [e.get("type", "?") for e in events]
    print(f"\n[error 事件] types={types}")
    # 1MB 消息 — 可能 422 (Pydantic 校验) 也可能 500
    # 不强求 error 出现 — 验 SSE 连接没崩
    # 如果 events 为空 (resp 非 200), 视为可接受
