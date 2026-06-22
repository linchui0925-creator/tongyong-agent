"""
delegate_task - 子 agent 委派工具

在现有 ToolRegistry / OpenAI function calling 协议上实现 Hermes 风格的多 agent：
- 单任务：直接 await 子 agent runner，避免线程开销
- 批量任务：asyncio 并发执行，默认最多 3 个
- 子 agent 使用独立 messages 上下文，不读父会话历史，不写记忆
"""

import asyncio
import contextvars
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.core.base import Message
from app.tools.registry import registry

logger = logging.getLogger(__name__)

MAX_DELEGATE_TASKS = 3
MAX_CHILD_TOOL_ROUNDS = 50          # 对齐 Hermes，默认 50（原 6 太小）
MAX_CHILD_SUMMARY_CHARS = 12_000
CHILD_WAIT_POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 30.0
DEFAULT_CHILD_TOOLSETS = ["web", "file"]
BLOCKED_CHILD_TOOLS = {
    "delegate_task",   # 禁止递归委派
    "ask",              # 禁止向用户提问
    "memory",           # 禁止写共享记忆
    "send_message",     # 禁止跨平台副作用
    "execute_code",     # 子 agent 应 step-by-step reasoning
}
MAX_DELEGATE_DEPTH = 1              # 父(0) → 子(1)，子不能再委派

# W4-10 P1-1 修复 2026-06-21: 用 ContextVar 替代模块级 int, 修复以下三个问题:
#   1. KeyboardInterrupt / 未走 finally 的异常会让全局计数不归零, 永久卡死
#   2. 同一进程多并发请求会相互污染 (即使 max=1)
#   3. uvicorn --workers>1 时每个 worker 独立, 但请求串扰风险仍在
# ContextVar 在 asyncio.Task.start() 时由 copy_context() 自动 copy,
# 任务结束 / reset() 后自动 GC, finally 配对使用可彻底解决以上问题。
_delegate_depth: contextvars.ContextVar[int] = contextvars.ContextVar("delegate_depth", default=0)


@dataclass(frozen=True)
class ChildTaskSpec:
    task_index: int
    goal: str
    context: str = ""
    toolsets: Optional[List[str]] = None

    @property
    def task_id(self) -> str:
        return f"child-{self.task_index}"


@dataclass
class ChildTaskState:
    spec: ChildTaskSpec
    status: str = "pending"
    summary: str = ""
    error: Optional[str] = None
    api_calls: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    last_activity_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_activity_at = time.time()

    def finish(self, status: str, summary: str = "", error: Optional[str] = None) -> None:
        self.status = status
        self.summary = summary
        self.error = error
        self.completed_at = time.time()
        self.touch()

    def to_result(self) -> Dict[str, Any]:
        end_time = self.completed_at or time.time()
        return {
            "task_index": self.spec.task_index,
            "task_id": self.spec.task_id,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
            "api_calls": self.api_calls,
            "tool_calls": self.tool_calls,
            "duration_seconds": round(end_time - self.started_at, 2),
        }


@dataclass
class DelegateRunState:
    run_id: str
    started_at: float = field(default_factory=time.time)
    last_heartbeat_at: float = field(default_factory=time.time)
    interrupt_requested: bool = False

    def request_interrupt(self) -> None:
        self.interrupt_requested = True


DELEGATE_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": "单个子 agent 要完成的明确目标。使用 tasks 时可省略。",
        },
        "context": {
            "type": "string",
            "description": "给子 agent 的必要背景。不会自动继承父会话历史。",
            "default": "",
        },
        "toolsets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "允许子 agent 使用的工具集，如 web、file、terminal、browser。默认 web/file。",
        },
        "tasks": {
            "type": "array",
            "maxItems": MAX_DELEGATE_TASKS,
            "description": "批量并行子任务。每项可包含 goal、context、toolsets。",
            "items": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "context": {"type": "string", "default": ""},
                    "toolsets": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["goal"],
            },
        },
    },
}


def _check_delegate() -> bool:
    return True


def _normalize_toolsets(toolsets: Optional[List[str]]) -> Set[str]:
    requested = [str(t).strip() for t in (toolsets or DEFAULT_CHILD_TOOLSETS) if str(t).strip()]
    resolved: Set[str] = set()
    for toolset in requested:
        alias_target = registry.get_toolset_alias_target(toolset)
        resolved.add(alias_target or toolset)
    return resolved


def _allowed_child_tool_names(toolsets: Optional[List[str]]) -> Set[str]:
    requested = _normalize_toolsets(toolsets)
    names: Set[str] = set()
    for entry in registry._snapshot_entries():
        if entry.name in BLOCKED_CHILD_TOOLS:
            continue
        if entry.toolset in requested:
            names.add(entry.name)
    return names


def _child_tool_schemas(toolsets: Optional[List[str]]) -> List[Dict[str, Any]]:
    return registry.get_definitions(_allowed_child_tool_names(toolsets), quiet=True)


def _build_child_system_prompt(goal: str, context: str, toolsets: Optional[List[str]]) -> str:
    allowed_tools = sorted(_allowed_child_tool_names(toolsets))
    allowed_text = ", ".join(allowed_tools) if allowed_tools else "无"
    return (
        "你是一个被父 agent 临时委派的子 agent。\n"
        "只完成当前目标，不要向用户提问，不要保存记忆，不要再次委派任务。\n"
        "可用工具只来自父 agent 授权后的交集；如果工具不足，直接说明限制。\n\n"
        f"目标：{goal}\n\n"
        f"背景：{context or '无'}\n\n"
        f"允许工具：{allowed_text}\n\n"
        "最终输出要求：给出可直接返回父 agent 的简洁结果，包含关键事实、来源或执行证据、失败原因。"
    )


def _parse_tool_args(raw_args: Any) -> Dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _get_current_llm():
    try:
        from app.services.llm_manager import get_llm_manager

        llm = get_llm_manager().get_current_llm()
        if llm is not None:
            return llm
    except Exception:
        logger.debug("从 LLMManager 获取 LLM 失败", exc_info=True)

    try:
        from app.main import agent_engine

        return getattr(agent_engine, "llm", None)
    except Exception:
        logger.debug("从 app.main 获取 AgentEngine LLM 失败", exc_info=True)
        return None


async def _run_child_agent(
    *,
    spec: ChildTaskSpec,
    run_state: Optional[DelegateRunState] = None,
) -> Dict[str, Any]:
    state = ChildTaskState(spec=spec, status="running")
    goal = spec.goal
    context = spec.context
    toolsets = spec.toolsets

    if not goal or not str(goal).strip():
        state.finish("failed", error="goal 不能为空")
        return state.to_result()

    try:
        llm = _get_current_llm()
        if llm is None:
            raise RuntimeError("LLM 未初始化")

        schemas = _child_tool_schemas(toolsets)
        allowed_tools = _allowed_child_tool_names(toolsets)
        messages: List[Message] = [
            Message(role="system", content=_build_child_system_prompt(goal, context, toolsets)),
            Message(role="user", content=str(goal).strip()),
        ]

        final_text = ""
        for round_num in range(MAX_CHILD_TOOL_ROUNDS):
            if run_state and run_state.interrupt_requested:
                state.finish("interrupted", error="父任务请求中断")
                return state.to_result()

            state.api_calls += 1
            state.touch()
            llm_response = await llm.chat(messages=messages, tools=schemas)
            state.touch()

            if not llm_response.has_tool_calls:
                final_text = llm_response.content or ""
                break

            tool_calls_data = []
            for tc in llm_response.tool_calls:
                tool_calls_data.append({
                    "id": tc.tool_call_id or str(uuid.uuid4()),
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                })

            messages.append(Message(role="assistant", content=json.dumps({
                "content": llm_response.content or "",
                "tool_calls": tool_calls_data,
            }, ensure_ascii=False)))

            for tc in llm_response.tool_calls:
                tool_name = tc.tool_name
                tool_call_id = tc.tool_call_id or str(uuid.uuid4())
                args = _parse_tool_args(tc.arguments)

                if tool_name not in allowed_tools:
                    state.tool_calls.append({
                        "tool_name": tool_name,
                        "status": "blocked",
                        "duration_seconds": 0.0,
                    })
                    result = {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "success": False,
                        "content": "",
                        "error_type": "not_allowed",
                        "error": f"子 agent 未获准使用工具: {tool_name}",
                    }
                else:
                    tool_started = time.time()
                    try:
                        state.tool_calls.append({
                            "tool_name": tool_name,
                            "status": "running",
                            "started_at": round(tool_started, 3),
                        })
                        tool_result = await registry.execute(tool_name, args)
                        state.touch()
                        success = not str(tool_result).startswith("工具执行失败")
                        state.tool_calls[-1].update({
                            "status": "completed" if success else "failed",
                            "duration_seconds": round(time.time() - tool_started, 2),
                        })
                        result = {
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "success": success,
                            "content": tool_result if success else "",
                            "error": "" if success else tool_result,
                            "duration_seconds": round(time.time() - tool_started, 2),
                        }
                    except Exception as exc:
                        state.tool_calls[-1].update({
                            "status": "failed",
                            "duration_seconds": round(time.time() - tool_started, 2),
                        })
                        result = {
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "success": False,
                            "content": "",
                            "error_type": "exception",
                            "error": str(exc),
                            "duration_seconds": round(time.time() - tool_started, 2),
                        }

                messages.append(Message(role="tool", content=json.dumps(result, ensure_ascii=False)))
        else:
            final_text = "子 agent 达到工具调用轮次上限，未生成最终总结。"

        if len(final_text) > MAX_CHILD_SUMMARY_CHARS:
            final_text = final_text[:MAX_CHILD_SUMMARY_CHARS] + (
                f"\n...（summary 过长，已截断至 {MAX_CHILD_SUMMARY_CHARS} 字符）"
            )

        state.finish("completed", summary=final_text, error=None)
        return state.to_result()
    except asyncio.CancelledError:
        state.finish("interrupted", error="子任务被取消")
        return state.to_result()
    except Exception as exc:
        logger.error("delegate_task 子任务失败: %s", exc, exc_info=True)
        state.finish("failed", error=str(exc))
        return state.to_result()


def _normalize_tasks(
    goal: Optional[str],
    context: str,
    toolsets: Optional[List[str]],
    tasks: Optional[List[Dict[str, Any]]],
) -> List[ChildTaskSpec]:
    if tasks:
        normalized: List[ChildTaskSpec] = []
        for index, raw in enumerate(tasks[:MAX_DELEGATE_TASKS]):
            if not isinstance(raw, dict):
                continue
            normalized.append(ChildTaskSpec(
                task_index=index,
                goal=str(raw.get("goal", "")).strip(),
                context=str(raw.get("context", context or "") or ""),
                toolsets=raw.get("toolsets") or toolsets,
            ))
        return normalized

    return [ChildTaskSpec(
        task_index=0,
        goal=str(goal or "").strip(),
        context=context or "",
        toolsets=toolsets,
    )]


async def _run_child_tasks_parallel(
    specs: List[ChildTaskSpec],
    run_state: DelegateRunState,
) -> List[Dict[str, Any]]:
    pending = {
        asyncio.create_task(_run_child_agent(spec=spec, run_state=run_state)): spec
        for spec in specs[:MAX_DELEGATE_TASKS]
    }
    results: List[Dict[str, Any]] = []

    while pending:
        done, still_pending = await asyncio.wait(
            pending.keys(),
            timeout=CHILD_WAIT_POLL_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )

        now = time.time()
        if now - run_state.last_heartbeat_at >= HEARTBEAT_SECONDS:
            logger.info(
                "delegate_task heartbeat: run=%s pending=%s completed=%s",
                run_state.run_id,
                len(still_pending),
                len(results),
            )
            run_state.last_heartbeat_at = now

        if run_state.interrupt_requested:
            for task in still_pending:
                task.cancel()

        for task in done:
            spec = pending.pop(task)
            try:
                results.append(task.result())
            except asyncio.CancelledError:
                results.append(ChildTaskState(spec=spec, status="interrupted").to_result())
            except Exception as exc:
                state = ChildTaskState(spec=spec, status="failed")
                state.finish("failed", error=str(exc))
                results.append(state.to_result())

        pending = {task: spec for task, spec in pending.items() if task in still_pending}

    results.sort(key=lambda item: item["task_index"])
    return results


async def delegate_task_tool(
    goal: Optional[str] = None,
    context: str = "",
    toolsets: Optional[List[str]] = None,
    tasks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    # W4-10 P1-1 修复: 用 ContextVar.set/reset 替代 global +=/-=
    # set() 返回 token, reset() 在 finally 中精确恢复到 set 之前的值,
    # 避免在嵌套/异常路径下计数漂移。
    run_state = DelegateRunState(run_id=str(uuid.uuid4()))
    depth_token = _delegate_depth.set(_delegate_depth.get() + 1)
    try:
        # ── 深度限制：子 agent 不能再次委派 ──
        if _delegate_depth.get() > MAX_DELEGATE_DEPTH:
            return json.dumps({
                "run_id": run_state.run_id,
                "results": [],
                "error": (
                    f"委派深度已达上限（{MAX_DELEGATE_DEPTH}层）。"
                    "子 agent 不能再次发起委派任务。"
                ),
            }, ensure_ascii=False)

        normalized_tasks = _normalize_tasks(goal, context, toolsets, tasks)
        if not normalized_tasks:
            return json.dumps({
                "run_id": run_state.run_id,
                "results": [],
                "error": "没有可执行的子任务",
            }, ensure_ascii=False)

        if len(normalized_tasks) == 1:
            spec = normalized_tasks[0]
            result = await _run_child_agent(spec=spec, run_state=run_state)
            return json.dumps({
                "run_id": run_state.run_id,
                "mode": "single",
                "results": [result],
                "duration_seconds": round(time.time() - run_state.started_at, 2),
            }, ensure_ascii=False)

        results = await _run_child_tasks_parallel(normalized_tasks, run_state)
        return json.dumps({
            "run_id": run_state.run_id,
            "mode": "parallel",
            "results": results,
            "duration_seconds": round(time.time() - run_state.started_at, 2),
        }, ensure_ascii=False)
    finally:
        _delegate_depth.reset(depth_token)


registry.register(
    name="delegate_task",
    toolset="agent",
    description=(
        "【并行执行首选】当任务可拆分为多个独立子任务时，必须优先使用此工具。\n"
        "典型场景：\n"
        "  • 同时搜索多个不同来源（搜索 A 和 B、查天气+查新闻）\n"
        "  • 并行分析多个文件/网页（分析这个文件夹里所有 py 文件）\n"
        "  • 互不依赖的调查任务（分别查 X 公司的股价和 Y 公司的财报）\n"
        "  • 需要多角度验证（从文档/代码/网络三个渠道查证）\n"
        "使用方式：单任务用 goal 参数；多任务（最多3个并行）用 tasks 参数。\n"
        "子 agent 不继承父会话历史，不写记忆，不能再次委派或提问。"
    ),
    schema=DELEGATE_TASK_SCHEMA,
    handler=delegate_task_tool,
    check_fn=_check_delegate,
    is_async=True,
    emoji="🔀",
    parallel_mode="never",
)
