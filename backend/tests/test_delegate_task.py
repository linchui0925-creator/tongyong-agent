import asyncio
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.base import LLMResponse, ToolCallResult
from app.tools.implementations import delegate_task as delegate_module
from app.tools.implementations.delegate_task import (
    _allowed_child_tool_names,
    _normalize_tasks,
    delegate_task_tool,
)
from app.tools.registry import registry


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def chat(self, messages, tools=None):
        self.calls += 1
        if not self.responses:
            return LLMResponse(content="done")
        response = self.responses.pop(0)
        if callable(response):
            return response(messages, tools)
        return response


class FakeAgentEngine:
    def __init__(self, llm):
        self.llm = llm


@pytest.mark.asyncio
async def test_delegate_task_single_task_returns_child_summary():
    llm = FakeLLM([LLMResponse(content="子任务完成")])

    with patch.object(delegate_module, "_get_current_llm", return_value=llm):
        raw = await delegate_task_tool(goal="总结 A")

    data = json.loads(raw)
    assert len(data["results"]) == 1
    assert data["mode"] == "single"
    assert data["run_id"]
    assert data["results"][0]["status"] == "completed"
    assert data["results"][0]["task_id"] == "child-0"
    assert data["results"][0]["summary"] == "子任务完成"
    assert data["results"][0]["api_calls"] == 1


@pytest.mark.asyncio
async def test_delegate_task_parallel_tasks_preserve_indexes():
    def response(messages, tools):
        goal = messages[-1].content
        return LLMResponse(content=f"完成: {goal}")

    llm = FakeLLM([response, response, response])
    tasks = [{"goal": "A"}, {"goal": "B"}, {"goal": "C"}]

    with patch.object(delegate_module, "_get_current_llm", return_value=llm):
        raw = await delegate_task_tool(tasks=tasks)

    data = json.loads(raw)
    assert data["mode"] == "parallel"
    assert [r["task_index"] for r in data["results"]] == [0, 1, 2]
    assert [r["task_id"] for r in data["results"]] == ["child-0", "child-1", "child-2"]
    assert [r["summary"] for r in data["results"]] == ["完成: A", "完成: B", "完成: C"]


@pytest.mark.asyncio
async def test_delegate_task_blocks_recursive_delegate_tool_call():
    llm = FakeLLM([
        LLMResponse(tool_calls=[
            ToolCallResult(
                tool_name="delegate_task",
                arguments={"goal": "递归"},
                tool_call_id="call_1",
            )
        ]),
        lambda messages, tools: LLMResponse(content=messages[-1].content),
    ])

    with patch.object(delegate_module, "_get_current_llm", return_value=llm):
        raw = await delegate_task_tool(goal="测试递归阻止", toolsets=["agent"])

    data = json.loads(raw)
    result = data["results"][0]
    assert result["status"] == "completed"
    assert result["tool_calls"][0]["status"] == "blocked"
    assert "未获准使用工具: delegate_task" in result["summary"]


def test_delegate_task_child_tool_allowlist_excludes_blocked_tools():
    registry.register(
        name="memory",
        toolset="memory",
        schema={"type": "object", "properties": {}},
        handler=lambda: "ok",
        is_async=False,
    )
    allowed = _allowed_child_tool_names(["agent", "memory"])
    assert "delegate_task" not in allowed
    assert "memory" not in allowed


def test_delegate_task_normalizes_task_specs_and_caps_count():
    specs = _normalize_tasks(
        goal=None,
        context="parent context",
        toolsets=["web"],
        tasks=[
            {"goal": "A"},
            {"goal": "B", "context": "own"},
            {"goal": "C"},
            {"goal": "D"},
        ],
    )

    assert len(specs) == 3
    assert [s.task_index for s in specs] == [0, 1, 2]
    assert [s.task_id for s in specs] == ["child-0", "child-1", "child-2"]
    assert specs[0].context == "parent context"
    assert specs[1].context == "own"


# ── W4-10 P1-1 修复回归测试 ─────────────────────────────
# ContextVar 替代模块级 int 后, 以下三个回归点必须被锁住:
#   1. 顺序调用不残留 (旧实现若 KeyboardInterrupt 跳过 finally 会卡死)
#   2. 并发任务互不污染 (旧实现同一进程内多请求会串扰)
#   3. 异常路径 finally 仍 reset (旧实现 try/finally 若子协程 raise 也会残留)


@pytest.mark.asyncio
async def test_delegate_depth_resets_between_sequential_calls():
    """
    P1-1 修复主目标 1: 顺序两次调用 delegate_task_tool,
    第二次进入时 _delegate_depth 应当从 0 重新开始, 而非 +1 累加。
    旧实现若 KeyboardInterrupt 在 += 1 之后 - 1 之前发生会永久卡死。
    """
    from app.tools.implementations.delegate_task import _delegate_depth

    # 模拟"上一次调用走到一半崩了", 旧实现下计数会残留
    # 新实现用 ContextVar.reset(token) 精确还原
    # 这里跑两次完整调用, 验证 _delegate_depth 回到 default (0)
    assert _delegate_depth.get() == 0  # 起点干净

    llm = FakeLLM([LLMResponse(content="ok"), LLMResponse(content="ok")])
    with patch.object(delegate_module, "_get_current_llm", return_value=llm):
        raw1 = await delegate_task_tool(goal="第一次")
        raw2 = await delegate_task_tool(goal="第二次")

    data1 = json.loads(raw1)
    data2 = json.loads(raw2)
    assert data1["results"][0]["status"] == "completed"
    assert data2["results"][0]["status"] == "completed"
    # ContextVar 在 finally 中 reset, 两次调用结束后回到 default
    assert _delegate_depth.get() == 0, (
        f"_delegate_depth should reset to 0 after both calls, got {_delegate_depth.get()}"
    )


@pytest.mark.asyncio
async def test_delegate_depth_isolated_across_concurrent_tasks():
    """
    P1-1 修复主目标 2: 两个并发 delegate_task 调用互不污染。
    旧实现: 进程级全局 int, 任务 A +1, 任务 B 看到 1 误以为已递归, 直接拒绝。
    新实现: ContextVar per-Task, asyncio.gather 启动的 Task 各自 copy_context。
    """
    from app.tools.implementations.delegate_task import _delegate_depth

    # 准备两个独立 LLM (各响应一次)
    llm1 = FakeLLM([LLMResponse(content="A 完成")])
    llm2 = FakeLLM([LLMResponse(content="B 完成")])

    async def call_with(llm, label):
        with patch.object(delegate_module, "_get_current_llm", return_value=llm):
            raw = await delegate_task_tool(goal=label)
        return json.loads(raw)

    # 并发启动: gather 自动 create_task, 每个 task 有独立 ContextVar copy
    results = await asyncio.gather(
        call_with(llm1, "并发任务 A"),
        call_with(llm2, "并发任务 B"),
    )

    # 两个任务都该跑通, 都不该被"假递归"挡住
    for data in results:
        assert len(data["results"]) == 1
        assert data["results"][0]["status"] == "completed", (
            f"并发调用被误判为递归: {data}"
        )

    # 跑完后 ContextVar 回到 default
    assert _delegate_depth.get() == 0


@pytest.mark.asyncio
async def test_delegate_depth_resets_on_exception():
    """
    P1-1 修复主目标 3: 子 agent 抛异常时, finally 仍要 reset ContextVar,
    后续调用不残留。
    """
    from app.tools.implementations.delegate_task import _delegate_depth

    # 让 LLM.chat 抛异常, 模拟 _run_child_agent 失败
    class BoomLLM:
        async def chat(self, messages, tools=None):
            raise RuntimeError("子 agent 崩了")

    llm = BoomLLM()
    with patch.object(delegate_module, "_get_current_llm", return_value=llm):
        # 异常会被 _run_child_agent 内部捕获, 不会真的抛出 delegate_task_tool
        # 但我们的目标是验证: 即便真的 raise, finally 也会 reset
        raw = await delegate_task_tool(goal="故意失败")

    data = json.loads(raw)
    # 子任务失败但函数本身正常返回 (delegate_task 内部有异常处理)
    assert data["results"][0]["status"] == "failed"
    # 关键: 即便走 finally, _delegate_depth 也要回到 0
    assert _delegate_depth.get() == 0, (
        f"异常路径后 _delegate_depth 未 reset, got {_delegate_depth.get()}"
    )


@pytest.mark.asyncio
async def test_delegate_depth_blocks_grandchild_recursion():
    """
    P1-1 边界: MAX=1 含义保持 — 父可调, 子被拒。
    模拟: 父 delegate_task → 子试图再次调用 delegate_task → 应被拒。
    """
    from app.tools.implementations.delegate_task import _delegate_depth, MAX_DELEGATE_DEPTH

    # 父层先 +1, 然后子层再 +1, 子层应看到 _delegate_depth == 2 > MAX
    parent_token = _delegate_depth.set(_delegate_depth.get() + 1)
    try:
        assert _delegate_depth.get() == 1  # 父 set 后

        # 模拟子层也调用 delegate_task_tool: 它内部会 set(+1)
        # 走工具的主流程, 第一次检查 _delegate_depth.get() > MAX_DELEGATE_DEPTH
        # 此时 == 2, > 1, 拒绝
        llm = FakeLLM([LLMResponse(content="不该被调到")])
        with patch.object(delegate_module, "_get_current_llm", return_value=llm):
            raw = await delegate_task_tool(goal="孙层调用")

        data = json.loads(raw)
        assert "error" in data
        assert "委派深度已达上限" in data["error"]
        # results 应为空 (被拒前就 return 了)
        assert data["results"] == []
    finally:
        _delegate_depth.reset(parent_token)

    # 验证: 父 finally reset 后, 回到 0
    assert _delegate_depth.get() == 0
