"""
TaskExecutionContext — 多智能体任务执行上下文

每个任务对应一个 ExecutionContext，封装：
- 任务记录（TaskRecord）
- 工作区（TaskWorkspace）
- 状态机（StateMachine）
- LLM Chat 循环（工具调用 + 状态追踪）
- EventBus 事件订阅

设计原则：
- 一个 Task 由一个 Agent 执行，创建自己的 ExecutionContext
- 代码/数据写 workspace 文件，不塞消息 content
- 工具调用结果记录到 context.tool_results，状态清晰
- EventBus 事件广播状态变化，其他 Agent 可感知

现有 agent.py 的 chat() 方法作为参考，提取共性：
- 20 轮工具调用上限
- 顺序执行每个 tool_call
- 结果塞 context.add_message()
- 执行声明校验

本模块的改进：
- 记录每个 tool_call 的状态（pending/executing/success/failure）
- workspace 文件替代大段 content
- EventBus 广播 progress/completed 等事件
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.core.multi_agent.state_machine import TaskState, TaskEvent, StateMachine
from app.core.multi_agent.event_bus import get_event_bus, Event
from app.core.multi_agent.workspace import TaskWorkspace, get_workspace

logger = logging.getLogger(__name__)

# 默认工具调用上限
DEFAULT_MAX_TOOL_ROUNDS = 20


# ══════════════════════════════════════════════════════════
# ToolCallState — 单次工具调用的状态
# ══════════════════════════════════════════════════════════

class ToolCallState(str, Enum):
    """单次工具调用的状态"""
    PENDING    = "pending"
    EXECUTING  = "executing"
    SUCCESS    = "success"
    FAILURE    = "failure"
    CANCELLED  = "cancelled"


@dataclass
class ToolCall:
    """单次工具调用的记录"""
    tool_call_id: str
    tool_name:    str
    arguments:    Dict[str, Any]
    state:        ToolCallState = ToolCallState.PENDING
    result:       str = ""
    error:        str = ""
    started_at:   Optional[str] = None
    ended_at:     Optional[str] = None
    duration_ms:  float = 0.0


# ══════════════════════════════════════════════════════════
# ExecutionResult — 执行结果
# ══════════════════════════════════════════════════════════

@dataclass
class ExecutionResult:
    """任务执行结果（结构化返回值）"""
    task_id:        str
    success:        bool
    response:       str               # LLM 最终回复文本
    tool_calls:     List[ToolCall]   # 所有工具调用记录
    tools_used:     List[str]        # 去重后的工具列表
    commands:       List[str]        # terminal 命令列表
    workspace_path: str = ""        # 工作区路径
    error:          str = ""        # 错误信息（执行异常）
    duration_ms:    float = 0.0     # 总耗时（毫秒）

    @property
    def tool_summary(self) -> str:
        """工具调用摘要（用于消息 content）"""
        if not self.tool_calls:
            return ""
        lines = []
        for tc in self.tool_calls:
            status = tc.state.value
            lines.append(f"- {tc.tool_name}: {status}" + (f" ({tc.error})" if tc.error else ""))
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# TaskExecutionContext — 执行上下文
# ══════════════════════════════════════════════════════════

class TaskExecutionContext:
    """
    任务执行上下文。
    
    封装单个任务的完整执行生命周期。
    
    使用示例:
    
        ctx = await TaskExecutionContext.create(
            task_id="t_001",
            session_id="s_001",
            agent_name="Coder",
            llm=llm,
            tool_mgr=tool_mgr,
        )
        
        # 事件驱动循环：等待自己的任务，认领后执行
        while True:
            event = await ctx.wait_for_event(...)
            if event.type == TaskEvent.CLAIMED.value and ctx.task_record:
                ctx.task_queue.claim(ctx.task_id, ctx.agent_name)
                result = await ctx.execute()
                
    状态流程:
        created → running → completed/failed/rejected
    """

    __slots__ = (
        "task_id", "session_id", "agent_name",
        "_record", "_workspace", "_sm",
        "_llm", "_tool_mgr", "_max_tool_rounds",
        "_tool_calls", "_messages",
        "_event_bus", "_queue",
        "_running", "_result",
    )

    def __init__(
        self,
        task_id: str,
        session_id: str,
        agent_name: str,
        llm: Any,
        tool_mgr: Any,
        record: Optional[Any] = None,
        workspace: Optional[TaskWorkspace] = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ):
        self.task_id = task_id
        self.session_id = session_id
        self.agent_name = agent_name
        self._record = record
        self._workspace = workspace
        self._sm = StateMachine(task_id, TaskState.PENDING)
        self._llm = llm
        self._tool_mgr = tool_mgr
        self._max_tool_rounds = max_tool_rounds
        self._tool_calls: List[ToolCall] = []
        self._messages: List[Any] = []   # [(role, content), ...]
        self._event_bus = get_event_bus()
        self._running = False
        self._result: Optional[ExecutionResult] = None

    # ── 工厂方法 ─────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        task_id: str,
        session_id: str,
        agent_name: str,
        llm: Any,
        tool_mgr: Any,
        db_path: str = "./data/team_sessions.db",
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ) -> "TaskExecutionContext":
        """
        异步工厂方法：创建并初始化上下文。
        
        从 TaskQueue 获取 record，从 Workspace 获取/创建工作区。
        """
        from app.core.multi_agent.task_queue import TaskQueue

        queue = TaskQueue(db_path)
        record = queue.get(task_id)

        ws = get_workspace(task_id, create=True)
        ws.init()

        ctx = cls(
            task_id=task_id,
            session_id=session_id,
            agent_name=agent_name,
            llm=llm,
            tool_mgr=tool_mgr,
            record=record,
            workspace=ws,
            max_tool_rounds=max_tool_rounds,
        )

        # 更新 record 的 workspace_path
        queue.update_workspace(task_id, str(ws.base))

        # 订阅事件总线
        ctx._event_bus.subscribe(
            agent_name=agent_name,
            task_ids=[task_id],
        )

        return ctx

    # ── 属性 ─────────────────────────────────────────

    @property
    def record(self) -> Optional[Any]:
        return self._record

    @property
    def workspace(self) -> TaskWorkspace:
        return self._workspace

    @property
    def state(self) -> TaskState:
        return self._sm.state

    @property
    def result(self) -> Optional[ExecutionResult]:
        return self._result

    @property
    def tool_calls(self) -> List[ToolCall]:
        return self._tool_calls

    # ── 消息 ─────────────────────────────────────────

    def add_message(self, role: str, content: str) -> None:
        """添加消息到上下文（role: user/assistant/system/tool）"""
        self._messages.append((role, content))

    def get_messages(self) -> List[Any]:
        """获取所有消息（用于 LLM chat）"""
        return [
            {"role": role, "content": content}
            for role, content in self._messages
        ]

    def clear_messages(self) -> None:
        """清空消息历史"""
        self._messages.clear()

    # ── 工具调用 ─────────────────────────────────────────

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_call_id: str = "",
    ) -> ToolCall:
        """
        执行单个工具调用（带状态追踪）。
        
        Returns:
            ToolCall 记录（含 state/result/error/duration）
        """
        tc = ToolCall(
            tool_call_id=tool_call_id or f"tc_{len(self._tool_calls)}",
            tool_name=tool_name,
            arguments=arguments,
            state=ToolCallState.EXECUTING,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._tool_calls.append(tc)
        t0 = time.monotonic()

        try:
            result = await self._tool_mgr.execute(tool_name, arguments)
            tc.state = ToolCallState.SUCCESS
            tc.result = result
        except Exception as e:
            tc.state = ToolCallState.FAILURE
            tc.error = str(e)
            tc.result = f"工具执行失败: {e}"
            logger.error(f"[ExecutionContext] 工具执行失败 {tool_name}: {e}")

        tc.ended_at = datetime.now(timezone.utc).isoformat()
        tc.duration_ms = (time.monotonic() - t0) * 1000

        # 工作区日志
        self._workspace.log(
            self.agent_name,
            f"[tool] {tool_name} → {tc.state.value} ({tc.duration_ms:.0f}ms)",
        )

        return tc

    # ── 核心执行循环 ─────────────────────────────────────────

    async def execute(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> ExecutionResult:
        """
        执行任务。
        
        流程：
        1. 状态机转换 pending/claimed → running
        2. 广播 task.started 事件
        3. LLM chat 循环（最多 max_tool_rounds 轮）
        4. 返回 ExecutionResult
        
        Args:
            prompt:       用户/上游给的任务描述
            system_prompt: Agent 的系统提示词
        
        Returns:
            ExecutionResult
        """
        from app.core.multi_agent.state_machine import TransitionError

        t0 = time.monotonic()
        self._running = True
        self._messages.clear()
        self._tool_calls.clear()

        # 系统消息先注入
        if system_prompt:
            self.add_message("system", system_prompt)
        self.add_message("user", prompt)

        # 状态机转换
        try:
            self._sm.transition_to(TaskState.RUNNING, self.agent_name)
        except TransitionError as e:
            logger.warning(f"[ExecutionContext] 状态转换失败: {e}")

        # 广播 started
        await self._event_bus.publish(
            event_type=TaskEvent.STARTED.value,
            payload={
                "task_id": self.task_id,
                "agent": self.agent_name,
            },
            source=self.agent_name,
            task_id=self.task_id,
            session_id=self.session_id,
        )

        try:
            response = await self._chat_with_tools()
            # 转换到 COMPLETED 状态
            try:
                self._sm.transition_to(TaskState.COMPLETED, self.agent_name)
            except TransitionError:
                pass
        except Exception as e:
            logger.error(f"[ExecutionContext] 执行异常: {e}", exc_info=True)
            response = f"执行异常: {e}"
            # 转换到 FAILED 状态
            try:
                self._sm.transition_to(TaskState.FAILED, self.agent_name)
            except TransitionError:
                pass

        # 工具去重
        tools_used = list(dict.fromkeys(tc.tool_name for tc in self._tool_calls))
        commands = [
            tc.arguments.get("command", "")
            for tc in self._tool_calls
            if tc.tool_name == "terminal" and tc.state == ToolCallState.SUCCESS
        ]

        success = self._sm.state == TaskState.COMPLETED
        result = ExecutionResult(
            task_id=self.task_id,
            success=success,
            response=response,
            tool_calls=list(self._tool_calls),
            tools_used=tools_used,
            commands=commands,
            workspace_path=str(self._workspace.base) if self._workspace else "",
            duration_ms=(time.monotonic() - t0) * 1000,
        )
        self._result = result
        return result

    async def _chat_with_tools(self) -> str:
        """
        LLM Chat 循环（带工具调用追踪）。
        
        参考 agent.py chat()，改进：
        - 每个 tool_call 记录 ToolCallState
        - 工具结果写 workspace 文件，不全塞消息
        - 广播 progress 事件
        """
        import json as _json

        tool_schemas = self._tool_mgr.get_schemas()
        commands_executed: List[str] = []

        for round_num in range(self._max_tool_rounds):
            messages = [
                {"role": role, "content": content}
                for role, content in self._messages
            ]

            logger.debug(f"[ExecutionContext] round={round_num} msg_count={len(messages)}")

            try:
                llm_response = await self._llm.chat(messages=messages, tools=tool_schemas)
            except Exception as e:
                logger.warning(f"[ExecutionContext] LLM 调用失败，降级为无工具: {e}")
                llm_response = await self._llm.chat(messages=messages, tools=None)
                response_text = llm_response.content or ""
                self.add_message("assistant", response_text)
                return response_text

            if not llm_response.has_tool_calls:
                # LLM 不再请求工具 → 正常退出
                response_text = llm_response.content or ""
                self.add_message("assistant", response_text)
                return response_text

            # 有工具调用：记录 assistant 消息
            tool_calls_data = []
            for tc_meta in llm_response.tool_calls:
                tool_calls_data.append({
                    "id": tc_meta.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tc_meta.tool_name,
                        "arguments": _json.dumps(tc_meta.arguments, ensure_ascii=False),
                    },
                })

            assistant_content = _json.dumps({
                "content": llm_response.content or "",
                "tool_calls": tool_calls_data,
            }, ensure_ascii=False)
            self.add_message("assistant", assistant_content)

            # 顺序执行每个工具调用
            for tc_meta in llm_response.tool_calls:
                logger.info(f"[ExecutionContext] 工具调用: {tc_meta.tool_name}")

                # 执行工具（带状态追踪）
                tc = await self.execute_tool(
                    tool_name=tc_meta.tool_name,
                    arguments=tc_meta.arguments,
                    tool_call_id=tc_meta.tool_call_id,
                )

                # 记录 terminal 命令
                if tc_meta.tool_name == "terminal":
                    commands_executed.append(tc_meta.arguments.get("command", ""))

                # 工具结果写消息（workspace 路径代替大段内容）
                # 如果结果超长，写文件，只在消息里放路径摘要
                result_for_llm = tc.result
                if len(tc.result) > 2000:
                    # 写文件
                    fname = f"tool_output_{tc.tool_name}_{tc.tool_call_id[:8]}.txt"
                    self._workspace.write("context", fname, tc.result)
                    result_for_llm = f"[output saved to workspace/{fname} ({len(tc.result)} chars)]"

                tool_msg_content = _json.dumps({
                    "tool_call_id": tc_meta.tool_call_id,
                    "content": f"[工具 {tc_meta.tool_name} 的返回结果]\n{result_for_llm}",
                }, ensure_ascii=False)
                self.add_message("tool", tool_msg_content)

            # 广播 progress
            await self._event_bus.publish(
                event_type=TaskEvent.PROGRESS.value,
                payload={
                    "task_id":    self.task_id,
                    "agent":      self.agent_name,
                    "round":      round_num + 1,
                    "max_rounds": self._max_tool_rounds,
                    "tools_used": [tc.tool_name for tc in self._tool_calls],
                },
                source=self.agent_name,
                task_id=self.task_id,
                session_id=self.session_id,
            )

        # 20 轮耗尽
        logger.warning(f"[ExecutionContext] 工具调用轮次耗尽 ({self._max_tool_rounds})")
        return "工具调用轮次已达上限，请基于已有结果回复。"

    # ── 事件等待 ─────────────────────────────────────────

    async def wait_for_event(
        self,
        event_types: Optional[List[str]] = None,
        timeout: Optional[float] = 30.0,
    ) -> Optional[Event]:
        """
        等待下一个匹配的事件（协程挂起，不轮询）。
        
        Args:
            event_types: 要监听的事件类型（空=全部）
            timeout:    等待超时
        
        Returns:
            Event 或 None（超时）
        """
        return await self._event_bus.next_event(self.agent_name, timeout=timeout)

    async def peek_events(self, max_count: int = 8) -> List[Event]:
        """非阻塞拉取多条事件"""
        return await self._event_bus.peek_events(self.agent_name, max_count=max_count)

    # ── 状态转换 ─────────────────────────────────────────

    async def mark_completed(self, result_summary: str = "") -> None:
        """标记任务完成并广播 completed 事件"""
        self._sm.transition_to(TaskState.COMPLETED, self.agent_name)
        await self._event_bus.publish(
            event_type=TaskEvent.COMPLETED.value,
            payload={
                "task_id":        self.task_id,
                "agent":          self.agent_name,
                "result_summary": result_summary,
                "workspace_path": str(self._workspace.base),
            },
            source=self.agent_name,
            task_id=self.task_id,
            session_id=self.session_id,
        )

    async def mark_failed(self, error: str = "") -> None:
        """标记任务失败并广播 failed 事件"""
        self._sm.transition_to(TaskState.FAILED, self.agent_name)
        await self._event_bus.publish(
            event_type=TaskEvent.FAILED.value,
            payload={
                "task_id": self.task_id,
                "agent":   self.agent_name,
                "error":   error,
            },
            source=self.agent_name,
            task_id=self.task_id,
            session_id=self.session_id,
        )

    async def mark_rejected(self, reason: str = "") -> None:
        """标记任务被拒绝并广播 rejected 事件"""
        self._sm.transition_to(TaskState.REJECTED, self.agent_name)
        await self._event_bus.publish(
            event_type=TaskEvent.REJECTED.value,
            payload={
                "task_id": self.task_id,
                "agent":   self.agent_name,
                "reason":  reason,
            },
            source=self.agent_name,
            task_id=self.task_id,
            session_id=self.session_id,
        )

    def __repr__(self) -> str:
        return f"<TaskExecutionContext task={self.task_id} agent={self.agent_name} state={self._sm.state.value}>"


# ══════════════════════════════════════════════════════════
# ToolCallManager — 工具调用状态管理（独立于 ExecutionContext）
# ══════════════════════════════════════════════════════════

class ToolCallManager:
    """
    管理单个任务内所有工具调用的状态。

    提供：
    - tool_call_id → ToolCall 映射查找
    - 每个 ToolCall 的状态转换追踪
    - 取消、重试、超时检测

    与 TaskExecutionContext 的关系：
    - ExecutionContext 用它追踪自己的 tool_calls
    - 也可以独立使用（纯状态管理，不执行工具）
    """

    __slots__ = ("_calls", "_lock")

    def __init__(self):
        self._calls: Dict[str, ToolCall] = {}
        self._lock = asyncio.Lock()

    # ── 注册 / 状态转换 ─────────────────────────────────

    def register(self, tool_call_id: str, tool_name: str, arguments: Dict[str, Any]) -> ToolCall:
        """注册一个新的工具调用（pending 状态）"""
        tc = ToolCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            state=ToolCallState.PENDING,
        )
        self._calls[tool_call_id] = tc
        return tc

    async def mark_executing(self, tool_call_id: str) -> Optional[ToolCall]:
        """标记为执行中（pending → executing）"""
        async with self._lock:
            tc = self._calls.get(tool_call_id)
            if tc is None:
                return None
            if tc.state != ToolCallState.PENDING:
                logger.warning(f"[ToolCallManager] {tool_call_id}: 不能从 {tc.state.value} 转为 executing")
                return None
            tc.state = ToolCallState.EXECUTING
            tc.started_at = datetime.now(timezone.utc).isoformat()
            return tc

    async def mark_success(self, tool_call_id: str, result: str) -> Optional[ToolCall]:
        """标记为成功（executing → success）"""
        async with self._lock:
            tc = self._calls.get(tool_call_id)
            if tc is None:
                return None
            tc.state = ToolCallState.SUCCESS
            tc.result = result
            tc.ended_at = datetime.now(timezone.utc).isoformat()
            if tc.started_at:
                start = datetime.fromisoformat(tc.started_at)
                tc.duration_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            return tc

    async def mark_failure(self, tool_call_id: str, error: str) -> Optional[ToolCall]:
        """标记为失败（executing → failure）"""
        async with self._lock:
            tc = self._calls.get(tool_call_id)
            if tc is None:
                return None
            tc.state = ToolCallState.FAILURE
            tc.error = error
            tc.ended_at = datetime.now(timezone.utc).isoformat()
            if tc.started_at:
                start = datetime.fromisoformat(tc.started_at)
                tc.duration_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            return tc

    async def mark_cancelled(self, tool_call_id: str) -> Optional[ToolCall]:
        """标记为取消"""
        async with self._lock:
            tc = self._calls.get(tool_call_id)
            if tc is None:
                return None
            tc.state = ToolCallState.CANCELLED
            tc.ended_at = datetime.now(timezone.utc).isoformat()
            return tc

    # ── 查询 ─────────────────────────────────────────

    def get(self, tool_call_id: str) -> Optional[ToolCall]:
        return self._calls.get(tool_call_id)

    def get_all(self) -> List[ToolCall]:
        return list(self._calls.values())

    def get_by_state(self, state: ToolCallState) -> List[ToolCall]:
        return [tc for tc in self._calls.values() if tc.state == state]

    @property
    def pending(self) -> List[ToolCall]:
        return self.get_by_state(ToolCallState.PENDING)

    @property
    def executing(self) -> List[ToolCall]:
        return self.get_by_state(ToolCallState.EXECUTING)

    @property
    def completed(self) -> List[ToolCall]:
        return self.get_by_state(ToolCallState.SUCCESS)

    @property
    def failed(self) -> List[ToolCall]:
        return self.get_by_state(ToolCallState.FAILURE)

    def is_all_done(self) -> bool:
        """所有工具调用都已终态（success/failure/cancelled）"""
        for tc in self._calls.values():
            if tc.state in (ToolCallState.PENDING, ToolCallState.EXECUTING):
                return False
        return True