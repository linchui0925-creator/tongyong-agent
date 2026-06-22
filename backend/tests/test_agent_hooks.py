"""
agent_hooks 测试 (W4-16 引入, 借鉴 learn-claude-code s04_hooks 模式)

覆盖:
1. HOOKS 注册表 + register/trigger/clear 基础 API
2. sync / async hook 都能被 trigger
3. 第一个非 None 返回值会被返回 (用于 PreToolUse 阻断)
4. hook 异常被捕获, 不破坏循环
5. setup_default_hooks 注册 4 个默认 hook
6. 4 个默认 hook 的行为:
   - hook_step_callback 调用 step_callback
   - hook_track_tool_used 追加 tool_name 到 tools_used
   - hook_post_tool_side_effects 写 commands_executed + record_tool_execution + tool_results_for_hermes
   - hook_memory_save 保存到 memory_storage + reset constraint_engine
"""

import asyncio
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.agent_hooks import (
    HOOKS,
    clear_hooks,
    list_hooks,
    register_hook,
    setup_default_hooks,
    trigger_hooks,
    trigger_hooks_async,
)


@pytest.fixture(autouse=True)
def _isolate_hooks():
    """每个测试前后清空 HOOKS, 避免污染"""
    clear_hooks()
    yield
    clear_hooks()


# ── 1. 基础 API ─────────────────────────────────

def test_hooks_registry_has_four_events():
    """HOOKS 字典必须包含 4 个核心事件 (s04_hooks 教学版)"""
    assert set(HOOKS.keys()) == {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}


def test_register_hook_appends_to_event():
    """register_hook 把 callback 追加到指定事件的列表"""
    def cb1(ctx): return None
    def cb2(ctx): return None
    register_hook("UserPromptSubmit", cb1)
    register_hook("UserPromptSubmit", cb2)
    assert HOOKS["UserPromptSubmit"] == [cb1, cb2]


def test_register_hook_rejects_unknown_event():
    """register_hook 抛 ValueError 当事件名不在 4 个核心事件里"""
    with pytest.raises(ValueError, match="Unknown hook event"):
        register_hook("NotAnEvent", lambda ctx: None)


def test_trigger_hooks_runs_all_in_order():
    """trigger_hooks 按注册顺序依次调用, 都返回 None 时整体返回 None"""
    calls = []
    register_hook("PreToolUse", lambda ctx: calls.append(("a", ctx["x"])))
    register_hook("PreToolUse", lambda ctx: calls.append(("b", ctx["x"])))
    result = trigger_hooks("PreToolUse", {"x": 1})
    assert result is None
    assert calls == [("a", 1), ("b", 1)]


def test_trigger_hooks_returns_first_nonnone():
    """trigger_hooks 遇到第一个非 None 返回值就停, 返回该值"""
    register_hook("PreToolUse", lambda ctx: None)
    register_hook("PreToolUse", lambda ctx: "BLOCKED")
    register_hook("PreToolUse", lambda ctx: "should not run")
    result = trigger_hooks("PreToolUse", {})
    assert result == "BLOCKED"


def test_trigger_hooks_catches_exceptions():
    """hook 抛异常时 trigger 不传播, 继续下一个 hook"""
    register_hook("PreToolUse", lambda ctx: 1 / 0)  # 抛 ZeroDivisionError
    register_hook("PreToolUse", lambda ctx: "ok")
    result = trigger_hooks("PreToolUse", {})
    # 第一个 hook 异常被吞, 第二个 hook "ok" 返回
    assert result == "ok"


def test_trigger_hooks_unknown_event_raises():
    """trigger_hooks 未知事件抛 ValueError"""
    with pytest.raises(ValueError, match="Unknown hook event"):
        trigger_hooks("NotAnEvent", {})


def test_clear_hooks_empties_all_events():
    """clear_hooks 清空所有事件"""
    register_hook("UserPromptSubmit", lambda ctx: None)
    register_hook("PreToolUse", lambda ctx: None)
    register_hook("PostToolUse", lambda ctx: None)
    register_hook("Stop", lambda ctx: None)
    clear_hooks()
    for cbs in HOOKS.values():
        assert cbs == []


def test_list_hooks_returns_callback_names():
    """list_hooks 返回 {event: [callback_name, ...]}"""
    def my_hook(ctx): return None
    register_hook("UserPromptSubmit", my_hook)
    result = list_hooks("UserPromptSubmit")
    assert result == {"UserPromptSubmit": ["my_hook"]}


# ── 2. async hooks ────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_hooks_async_awaits_coroutine():
    """trigger_hooks_async 正确 await async 回调"""
    async def async_hook(ctx):
        await asyncio.sleep(0.001)
        return "async_done"
    register_hook("UserPromptSubmit", async_hook)
    result = await trigger_hooks_async("UserPromptSubmit", {})
    assert result == "async_done"


@pytest.mark.asyncio
async def test_trigger_hooks_async_with_sync_hook():
    """async trigger 也能跑 sync hook"""
    register_hook("UserPromptSubmit", lambda ctx: "sync")
    result = await trigger_hooks_async("UserPromptSubmit", {})
    assert result == "sync"


# ── 3. setup_default_hooks ─────────────────────────

def test_setup_default_hooks_registers_four():
    """setup_default_hooks 注册 4 个事件各至少 1 个 hook"""
    setup_default_hooks()
    listed = list_hooks()
    for ev in ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]:
        assert ev in listed
        assert len(listed[ev]) >= 1, f"{ev} 应当至少注册 1 个 hook"


# ── 4. 默认 hook 行为 ──────────────────────────────

def test_default_step_callback_hook():
    """UserPromptSubmit 默认 hook: 调用 step_callback 并捕获异常"""
    setup_default_hooks()
    called_with = []
    def step_cb(payload):
        called_with.append(payload)
    trigger_hooks("UserPromptSubmit", {
        "round": 3,
        "remaining": 7,
        "context": MagicMock(get_messages=lambda: [1, 2, 3, 4, 5]),
        "step_callback": step_cb,
    })
    assert len(called_with) == 1
    assert called_with[0]["round"] == 3
    assert called_with[0]["remaining"] == 7
    assert called_with[0]["messages_count"] == 5


def test_default_step_callback_handles_none():
    """UserPromptSubmit 默认 hook 在 step_callback=None 时不抛"""
    setup_default_hooks()
    result = trigger_hooks("UserPromptSubmit", {
        "round": 1, "remaining": 10, "context": None, "step_callback": None,
    })
    assert result is None


def test_default_step_callback_catches_exception():
    """step_callback 抛错时, hook 不向上传"""
    setup_default_hooks()
    def bad_cb(payload):
        raise RuntimeError("frontend disconnected")
    # 不应抛
    trigger_hooks("UserPromptSubmit", {
        "round": 1, "remaining": 10, "context": None, "step_callback": bad_cb,
    })


def test_default_track_tool_used_hook():
    """PreToolUse 默认 hook: 追加 tool_name 到 tools_used"""
    setup_default_hooks()
    tools_used = []
    trigger_hooks("PreToolUse", {"tool_name": "read_file", "tools_used": tools_used})
    trigger_hooks("PreToolUse", {"tool_name": "grep", "tools_used": tools_used})
    assert tools_used == ["read_file", "grep"]


def test_default_post_tool_side_effects_terminal():
    """PostToolUse 默认 hook: terminal 命令追加到 commands_executed"""
    setup_default_hooks()
    engine = MagicMock()
    commands_executed = []
    trigger_hooks("PostToolUse", {
        "tool_name": "terminal",
        "arguments": {"command": "ls -la"},
        "result": "file1\nfile2",
        "is_error": False,
        "constraint_engine": engine,
        "commands_executed": commands_executed,
        "tool_results_for_hermes": [],
    })
    assert commands_executed == ["ls -la"]


def test_default_post_tool_side_effects_non_terminal():
    """PostToolUse 默认 hook: 非 terminal 工具不追加 commands_executed"""
    setup_default_hooks()
    engine = MagicMock()
    commands_executed = []
    trigger_hooks("PostToolUse", {
        "tool_name": "read_file",
        "arguments": {"path": "/tmp/x"},
        "result": "content",
        "is_error": False,
        "constraint_engine": engine,
        "commands_executed": commands_executed,
        "tool_results_for_hermes": [],
    })
    assert commands_executed == []  # 非 terminal, 不追加


def test_default_post_tool_side_effects_records_to_engine():
    """PostToolUse 默认 hook: 调用 constraint_engine.record_tool_execution"""
    setup_default_hooks()
    engine = MagicMock()
    hermes = []
    trigger_hooks("PostToolUse", {
        "tool_name": "read_file",
        "arguments": {"path": "/etc/hosts"},
        "result": "127.0.0.1 localhost",
        "is_error": False,
        "elapsed": 0.05,
        "constraint_engine": engine,
        "commands_executed": [],
        "tool_results_for_hermes": hermes,
    })
    engine.record_tool_execution.assert_called_once()
    call = engine.record_tool_execution.call_args
    assert call.kwargs["tool_name"] == "read_file"
    assert call.kwargs["success"] is True
    assert hermes == [("read_file", "127.0.0.1 localhost")]


def test_default_post_tool_side_effects_no_engine():
    """PostToolUse 默认 hook 在 constraint_engine=None 时不抛"""
    setup_default_hooks()
    # 不应抛
    trigger_hooks("PostToolUse", {
        "tool_name": "read_file",
        "arguments": {},
        "result": "x",
        "is_error": False,
        "constraint_engine": None,
        "commands_executed": [],
        "tool_results_for_hermes": [],
    })


# ── 5. Stop hook (memory save) ──────────────────────

@pytest.mark.asyncio
async def test_default_memory_save_hook():
    """Stop 默认 hook: 保存到 memory_storage + 重置 constraint_engine"""
    setup_default_hooks()
    storage = MagicMock()
    storage.add_message = MagicMock(return_value=asyncio.Future())
    storage.add_message.return_value.set_result(None)
    engine = MagicMock()

    await trigger_hooks_async("Stop", {
        "context": MagicMock(),
        "final_response_chunks": ["这是 ", "最终 ", "回复"],
        "tools_used": ["read_file"],
        "commands_executed": ["ls"],
        "session_id": "sess-1",
        "message": "用户消息",
        "memory_storage": storage,
        "constraint_engine": engine,
    })
    # 验证 add_message 被调用 2 次 (user + assistant)
    assert storage.add_message.call_count == 2
    user_call = storage.add_message.call_args_list[0]
    assert user_call.args == ("sess-1", "user", "用户消息")
    asst_call = storage.add_message.call_args_list[1]
    assert asst_call.args[0] == "sess-1"
    assert asst_call.args[1] == "assistant"
    assert "这是 最终 回复" in asst_call.args[2]
    # 重置引擎
    engine.reset_session.assert_called_once()


@pytest.mark.asyncio
async def test_default_memory_save_cleans_thinking_tags():
    """Stop hook: 清理 <think> 标签不存入数据库"""
    setup_default_hooks()
    storage = MagicMock()
    storage.add_message = MagicMock(return_value=asyncio.Future())
    storage.add_message.return_value.set_result(None)
    await trigger_hooks_async("Stop", {
        "context": MagicMock(),
        "final_response_chunks": ["<think>\n思考过程\n</think>\n最终答案"],
        "session_id": "s1",
        "message": "q",
        "memory_storage": storage,
        "constraint_engine": None,
    })
    asst_call = storage.add_message.call_args_list[1]
    # <think>...</think> 应当被剥离
    assert "<think>" not in asst_call.args[2]
    assert "最终答案" in asst_call.args[2]


@pytest.mark.asyncio
async def test_default_memory_save_no_storage():
    """Stop hook 在 memory_storage=None 时不抛"""
    setup_default_hooks()
    await trigger_hooks_async("Stop", {
        "context": MagicMock(),
        "final_response_chunks": [],
        "session_id": "s1",
        "message": "q",
        "memory_storage": None,
        "constraint_engine": None,
    })
    # 不应抛


# ── 6. 注册自定义 hook 与默认 hook 协同 ─────────────

def test_custom_hook_runs_alongside_defaults():
    """用户注册的 hook 跟默认 hook 一起跑, 顺序按注册先后"""
    clear_hooks()
    setup_default_hooks()
    custom_calls = []
    register_hook("PreToolUse", lambda ctx: custom_calls.append(ctx["tool_name"]))
    trigger_hooks("PreToolUse", {
        "tool_name": "read_file",
        "tools_used": [],  # 默认 hook 要这个 key
    })
    # 自定义 hook 应当被调用
    assert custom_calls == ["read_file"]


def test_pretooluse_block_semantic():
    """PreToolUse hook 返回非 None 时 trigger 返回该值, 用于阻断"""
    clear_hooks()
    register_hook("PreToolUse", lambda ctx: "denied by hook" if ctx["tool_name"] == "rm" else None)
    # rm 应当被阻断
    result = trigger_hooks("PreToolUse", {"tool_name": "rm"})
    assert result == "denied by hook"
    # read_file 不阻断
    result = trigger_hooks("PreToolUse", {"tool_name": "read_file"})
    assert result is None
