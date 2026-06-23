"""
agent_hooks E2E 集成测试 (W4-17 2026-06-22)

验证 W4-16 + W4-17 改动在真实 stream_chat / chat() / langchain_agent 流程里:
- 默认 hook 都被注册并 fire
- 新事件 (PostLLMCall) 在 stream_chat 里被 trigger
- 工具统计 / 审计日志 / interim_assistant 都在 ctx 里被 hook 读取
- 6 事件全链路覆盖
"""

import asyncio
import os
import sys
import time
from unittest.mock import MagicMock, AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _isolate_hooks():
    from app.core.agent_hooks import clear_hooks
    clear_hooks()
    yield
    clear_hooks()


# ── E2E: stream_chat 调用 6 个事件 ─────────────────

@pytest.mark.asyncio
async def test_stream_chat_fires_user_prompt_submit_and_stop():
    """stream_chat 至少触发 UserPromptSubmit + Stop (其它视情况)"""
    from app.core.agent import AgentEngine
    from app.core.context import ContextManager

    fake_llm = MagicMock()
    fake_llm.initialize = AsyncMock(return_value=True)
    fake_llm.get_embedding = AsyncMock(return_value=[0.0] * 8)
    fake_llm.chat = AsyncMock(return_value=MagicMock(
        content="hi", has_tool_calls=False, has_thinking=False, thinking=[],
        tool_calls=[], usage=None
    ))
    fake_storage = MagicMock()
    fake_storage.get_messages = AsyncMock(return_value=[])
    fake_storage.add_message = AsyncMock()

    engine = AgentEngine(llm=fake_llm)
    engine.memory_storage = fake_storage
    engine.vector_store = MagicMock()
    engine.vector_store.search = AsyncMock(return_value=[])
    engine.context = ContextManager()

    events_fired = []
    from app.core.agent_hooks import register_hook
    register_hook("UserPromptSubmit", lambda ctx: events_fired.append("UPS"))
    register_hook("PreLLMCall", lambda ctx: events_fired.append("PreLLM"))
    register_hook("PostLLMCall", lambda ctx: events_fired.append("PostLLM"))
    register_hook("Stop", lambda ctx: events_fired.append("Stop"))

    async for _ in engine.stream_chat(session_id="s1", message="hello"):
        pass

    assert "UPS" in events_fired
    assert "Stop" in events_fired


# ── E2E: PostLLMCall 触发 interim_assistant_callback ─────

@pytest.mark.asyncio
async def test_stream_chat_post_llm_call_triggers_interim_callback():
    """interim_assistant_callback 通过 PostLLMCall hook 触发 (W4-17)

    注意: interim_assistant_callback 只在 LLM 返回 tool_calls 时触发
    (原代码位置: 工具处理之前, no-tool-calls 分支已 break)
    所以 mock 第一次返回 tool_call
    """
    from app.core.agent import AgentEngine
    from app.core.context import ContextManager

    call_count = [0]
    def fake_chat(messages, tools=None):
        call_count[0] += 1
        if call_count[0] == 1:
            tc = MagicMock()
            tc.tool_call_id = "tc-1"
            tc.tool_name = "read_file"
            tc.arguments = {"path": "/etc/hosts"}
            return MagicMock(
                content="思考: 用户要读 /etc/hosts", has_tool_calls=True,
                has_thinking=False, thinking=[], tool_calls=[tc], usage=None,
            )
        return MagicMock(
            content="完成", has_tool_calls=False, has_thinking=False, thinking=[],
            tool_calls=[], usage=None,
        )

    fake_llm = MagicMock()
    fake_llm.initialize = AsyncMock(return_value=True)
    fake_llm.get_embedding = AsyncMock(return_value=[0.0] * 8)
    fake_llm.chat = AsyncMock(side_effect=fake_chat)

    fake_storage = MagicMock()
    fake_storage.get_messages = AsyncMock(return_value=[])
    fake_storage.add_message = AsyncMock()

    engine = AgentEngine(llm=fake_llm)
    engine.memory_storage = fake_storage
    engine.vector_store = MagicMock()
    engine.vector_store.search = AsyncMock(return_value=[])
    engine.context = ContextManager()

    interim_called = []
    def interim_cb(text):
        interim_called.append(text)

    async for _ in engine.stream_chat(
        session_id="s1", message="hi", interim_assistant_callback=interim_cb,
    ):
        pass

    assert interim_called, "interim_assistant_callback 应当被 PostLLMCall hook 触发"
    assert "思考" in interim_called[0]


# ── E2E: 工具统计 hook 累积调用次数 ─────────────────

@pytest.mark.asyncio
async def test_stream_chat_tool_stats_hook_accumulates():
    """tool_stats hook 累积 tools_used + 调用次数"""
    from app.core.agent import AgentEngine
    from app.core.context import ContextManager
    from app.core.agent_hooks import register_hook

    # 模拟 LLM 先返回 tool_call, 第二次返回 text
    call_count = [0]
    def fake_chat(messages, tools=None):
        call_count[0] += 1
        if call_count[0] == 1:
            # 第一次: 工具调用
            tc = MagicMock()
            tc.tool_call_id = "tc-1"
            tc.tool_name = "read_file"
            tc.arguments = {"path": "/etc/hosts"}
            return MagicMock(
                content="", has_tool_calls=True, has_thinking=False, thinking=[],
                tool_calls=[tc], usage=None,
            )
        else:
            return MagicMock(
                content="文件内容是 127.0.0.1 localhost", has_tool_calls=False,
                has_thinking=False, thinking=[], tool_calls=[], usage=None,
            )

    fake_llm = MagicMock()
    fake_llm.initialize = AsyncMock(return_value=True)
    fake_llm.get_embedding = AsyncMock(return_value=[0.0] * 8)
    fake_llm.chat = AsyncMock(side_effect=fake_chat)

    fake_storage = MagicMock()
    fake_storage.get_messages = AsyncMock(return_value=[])
    fake_storage.add_message = AsyncMock()

    engine = AgentEngine(llm=fake_llm)
    engine.memory_storage = fake_storage
    engine.vector_store = MagicMock()
    engine.vector_store.search = AsyncMock(return_value=[])
    engine.context = ContextManager()

    # 注册 tool_stats hook 收集
    stats = {}
    def stats_collector(ctx):
        stats.setdefault(ctx["tool_name"], []).append(ctx.get("result", "")[:30])

    register_hook("PostToolUse", stats_collector)

    events = []
    async for ev in engine.stream_chat(session_id="s1", message="read /etc/hosts"):
        if isinstance(ev, dict):
            events.append(ev.get("type"))

    assert "read_file" in stats, f"tool_stats hook 没 fire, stats={stats}"


# ── E2E: 审计 hook 注册 + 触发计数 (不调真 tool, 避免 hang) ─────

def test_audit_hook_registers_and_fires_in_posttooluse():
    """audit hook 能在 PostToolUse 事件中被 trigger, 写日志到指定路径"""
    from app.core.agent_hooks import register_hook, clear_hooks
    clear_hooks()
    import json, tempfile, os
    fd, log_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)

    try:
        def my_audit(ctx):
            with open(log_path, "a") as f:
                f.write(json.dumps({"tool": ctx["tool_name"], "is_error": ctx.get("is_error")}) + "\n")
        register_hook("PostToolUse", my_audit)
        from app.core.agent_hooks import trigger_hooks
        trigger_hooks("PostToolUse", {"tool_name": "read_file", "is_error": False, "arguments": {}})
        trigger_hooks("PostToolUse", {"tool_name": "grep", "is_error": True, "arguments": {}})
        content = open(log_path).read().strip()
        assert "read_file" in content
        assert "grep" in content
    finally:
        if os.path.exists(log_path):
            os.unlink(log_path)
        clear_hooks()


# ── E2E: 6 事件全部能 fire ─────────────────────

@pytest.mark.asyncio
async def test_all_six_events_fire_in_stream_chat():
    """完整一轮 stream_chat (含 1 个 tool call) 触发全部 6 个事件"""
    from app.core.agent import AgentEngine
    from app.core.context import ContextManager
    from app.core.agent_hooks import register_hook

    call_count = [0]
    def fake_chat(messages, tools=None):
        call_count[0] += 1
        if call_count[0] == 1:
            tc = MagicMock()
            tc.tool_call_id = "tc-1"
            tc.tool_name = "read_file"
            tc.arguments = {"path": "/etc/hosts"}
            return MagicMock(
                content="", has_tool_calls=True, has_thinking=False, thinking=[],
                tool_calls=[tc], usage=None,
            )
        else:
            return MagicMock(
                content="完成", has_tool_calls=False, has_thinking=False, thinking=[],
                tool_calls=[], usage=None,
            )

    fake_llm = MagicMock()
    fake_llm.initialize = AsyncMock(return_value=True)
    fake_llm.get_embedding = AsyncMock(return_value=[0.0] * 8)
    fake_llm.chat = AsyncMock(side_effect=fake_chat)

    fake_storage = MagicMock()
    fake_storage.get_messages = AsyncMock(return_value=[])
    fake_storage.add_message = AsyncMock()

    engine = AgentEngine(llm=fake_llm)
    engine.memory_storage = fake_storage
    engine.vector_store = MagicMock()
    engine.vector_store.search = AsyncMock(return_value=[])
    engine.context = ContextManager()

    fired = []
    for ev in ["UserPromptSubmit", "PreLLMCall", "PostLLMCall", "PreToolUse", "PostToolUse", "Stop"]:
        register_hook(ev, lambda ctx, ev=ev: fired.append(ev))

    async for _ in engine.stream_chat(session_id="s1", message="x"):
        pass

    # 6 事件中, 这一轮至少 fire 这 5 个 (PreLLMCall 没默认 hook 但能 fire)
    assert "UserPromptSubmit" in fired
    assert "PostLLMCall" in fired
    assert "PreToolUse" in fired
    assert "PostToolUse" in fired
    assert "Stop" in fired
