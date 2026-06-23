"""
agent_hooks - Agent 循环钩子注册表

W4-16 (2026-06-22) 引入: 借鉴 learn-claude-code s04_hooks 模式。

设计原则:
  - 循环是稳定的核心, 扩展行为都注册成 hooks
  - 循环只调用 trigger_hooks(event, ctx), 不知道具体逻辑
  - 加新功能 (如: 自动 git commit / Slack 通知 / 工具白名单) 只需要
    register_hook() 一行, 不再改 agent.py 的 while 循环

6 个事件对应 agent cycle 关键节点 (W4-17 扩展):
  - UserPromptSubmit: 每轮 LLM 调用前
  - PreLLMCall: LLM API 实际调用前 (可选 hook, 供 budget / cache / 替换用)
  - PostLLMCall: LLM 返回后, 工具处理前 (interim_assistant 流式回调)
  - PreToolUse: 每个工具调用前 (可返回非 None 阻断)
  - PostToolUse: 每个工具调用后
  - Stop: 循环退出前 (收尾)

参考:
  - https://github.com/shareAI-lab/learn-claude-code/blob/main/s04_hooks/README.md
  - CC 源码 coreTypes.ts:25-53 (实际有 27 个事件, 教学版简化 4 个)
"""

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 4 个核心事件 (与 s04_hooks 教学版对齐)
HOOKS: Dict[str, List[Callable]] = {
    "UserPromptSubmit": [],
    "PreLLMCall": [],       # W4-17: LLM 调用前 (供 LLM-level 拦截 / 缓存 / budget 检查)
    "PostLLMCall": [],      # W4-17: LLM 返回后, 工具处理前 (供 interim_assistant 流式回调)
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}

# Hook 事件类型定义
HookEvent = str  # "UserPromptSubmit" | "PreToolUse" | "PostToolUse" | "Stop"


def register_hook(event: HookEvent, callback: Callable) -> None:
    """注册一个 hook 回调到指定事件

    Args:
        event: 6 个事件之一 (UserPromptSubmit / PreLLMCall / PostLLMCall / PreToolUse / PostToolUse / Stop)
        callback: 回调函数, 接收一个 ctx dict 参数
                  - UserPromptSubmit: ctx 包含 round, remaining, context, session_id, message, step_callback
                  - PreToolUse: ctx 包含 tool_name, arguments, tool_call_id, context
                                 返回非 None 会阻断工具执行 (作为错误消息)
                  - PostToolUse: ctx 包含 tool_name, arguments, result, is_error, elapsed,
                                 tool_call_id, context, constraint_engine, tools_used,
                                 commands_executed, tool_results_for_hermes
                  - Stop: ctx 包含 context, final_response_chunks, tools_used,
                          commands_executed, session_id, message, memory_storage,
                          constraint_engine
    """
    if event not in HOOKS:
        raise ValueError(
            f"Unknown hook event: {event!r}. Valid: {list(HOOKS.keys())}"
        )
    HOOKS[event].append(callback)
    logger.debug(f"registered hook {callback.__name__!r} for event {event!r}")


def trigger_hooks(event: HookEvent, ctx: Dict[str, Any]) -> Optional[Any]:
    """触发指定事件的所有 hook, 返回第一个非 None 的结果

    支持 sync / async 回调, 自动 await coroutine

    Returns:
        - None: 所有 hook 都没说"停"
        - 非 None: 第一个返回非 None 的 hook 的返回值
                  (PreToolUse 用作阻断消息, PostToolUse 用作 __BLOCK__ 标记)
    """
    if event not in HOOKS:
        raise ValueError(f"Unknown hook event: {event!r}")
    for cb in HOOKS[event]:
        try:
            result = cb(ctx)
            if inspect.iscoroutine(result):
                # 同步 trigger 不应被 async 回调卡住, 给个警告 + 退化
                logger.warning(
                    f"hook {cb.__name__!r} returned coroutine but trigger_hooks "
                    f"is sync; use trigger_hooks_async for async hooks"
                )
                continue
            if result is not None:
                return result
        except Exception as e:
            logger.warning(f"hook {cb.__name__!r} raised: {e}", exc_info=False)
    return None


async def trigger_hooks_async(event: HookEvent, ctx: Dict[str, Any]) -> Optional[Any]:
    """trigger_hooks 的 async 版本, 正确 await coroutine 回调

    agent 主循环用这个版本, 允许 hook 是 async 函数
    """
    if event not in HOOKS:
        raise ValueError(f"Unknown hook event: {event!r}")
    for cb in HOOKS[event]:
        try:
            result = cb(ctx)
            if inspect.iscoroutine(result):
                result = await result
            if result is not None:
                return result
        except Exception as e:
            logger.warning(f"hook {cb.__name__!r} raised: {e}", exc_info=False)
    return None


def clear_hooks() -> None:
    """清空所有 hook (测试用, 避免 hook 污染其他测试)"""
    for k in HOOKS:
        HOOKS[k].clear()


def list_hooks(event: Optional[HookEvent] = None) -> Dict[str, List[str]]:
    """列出已注册的 hook (调试用)"""
    if event:
        return {event: [getattr(cb, "__name__", repr(cb)) for cb in HOOKS[event]]}
    return {
        ev: [getattr(cb, "__name__", repr(cb)) for cb in cbs]
        for ev, cbs in HOOKS.items()
    }


# ── 默认 hook 注册 (agent 启动时调一次) ─────────────

def setup_default_hooks(get_time: Callable[[], float] = None) -> None:
    """注册 agent 默认的扩展行为 hook

    这些 hook 是把"原 loop 里的内联副作用"提取出来, 行为完全等价
    (只是从循环里挪到了循环外的注册表里)

    Args:
        get_time: time.time 的可注入函数, 测试时可换 fake
    """
    _time = get_time or (lambda: __import__("time").time())

    def hook_step_callback(ctx: Dict[str, Any]) -> None:
        """UserPromptSubmit: 调用外部 step_callback (前端进度 / 心跳等)"""
        cb = ctx.get("step_callback")
        if cb is None:
            return None
        try:
            cb({
                "round": ctx.get("round", 0),
                "remaining": ctx.get("remaining", 0),
                "messages_count": len(ctx.get("context").get_messages())
                    if ctx.get("context") else 0,
            })
        except Exception as e:
            logger.warning(f"step_callback 执行失败: {e}")
        return None

    def hook_track_tool_used(ctx: Dict[str, Any]) -> None:
        """PreToolUse: 工具调用前先登记到 tools_used (供 _validate_execution_claim 用)"""
        tools_used = ctx.get("tools_used")
        if tools_used is not None:
            tools_used.append(ctx["tool_name"])
        return None

    def hook_post_tool_side_effects(ctx: Dict[str, Any]) -> None:
        """PostToolUse: 工具调用后, 把副作用集中处理

        1. terminal 命令追加到 commands_executed (供 _validate_execution_claim 用)
        2. constraint engine 记录 (防 agent 幻觉)
        3. tool_results_for_hermes 追加 (供 should_continue_loop 判定)
        """
        tool_name = ctx["tool_name"]
        args = ctx.get("arguments", {})
        tool_result = ctx.get("result", "")
        is_error = ctx.get("is_error", False)
        commands_executed = ctx.get("commands_executed")
        if tool_name == "terminal" and commands_executed is not None:
            commands_executed.append(args.get("command", ""))

        constraint_engine = ctx.get("constraint_engine")
        tool_results_for_hermes = ctx.get("tool_results_for_hermes")
        if constraint_engine is not None:
            try:
                constraint_engine.record_tool_execution(
                    tool_name=tool_name,
                    arguments=args,
                    result=tool_result,
                    success=not is_error,
                    timestamp=_time(),
                )
            except Exception as e:
                logger.warning(f"constraint_engine.record_tool_execution failed: {e}")
            if tool_results_for_hermes is not None:
                tool_results_for_hermes.append((tool_name, tool_result))
        return None

    async def hook_memory_save(ctx: Dict[str, Any]) -> None:
        """Stop: 收尾 - 保存 user / assistant 消息到 memory_storage, 重置约束引擎"""
        memory_storage = ctx.get("memory_storage")
        session_id = ctx.get("session_id")
        message = ctx.get("message")
        final_chunks = ctx.get("final_response_chunks") or []
        constraint_engine = ctx.get("constraint_engine")

        if memory_storage is not None and session_id and message:
            final_reply = "".join(final_chunks).strip()
            if not final_reply:
                final_reply = "（无回复内容）"
            # 清理 <think>...</think> 思考标签, 不存入数据库
            import re
            final_reply = re.sub(r'<think>[\s\S]*?</think>', '', final_reply, flags=re.DOTALL).strip()
            final_reply = re.sub(r'<think>[\s\S]*?</think>', '', final_reply, flags=re.DOTALL).strip()
            final_reply = re.sub(r'<\|im_start\|[^|]*\|[^>]*>[\s\S]*?<\|im_end\|>', '', final_reply).strip()
            try:
                await memory_storage.add_message(session_id, "user", message)
                await memory_storage.add_message(session_id, "assistant", final_reply)
            except Exception as e:
                logger.warning(f"memory save failed: {e}")

        if constraint_engine is not None:
            try:
                constraint_engine.reset_session()
            except Exception as e:
                logger.warning(f"constraint_engine.reset_session failed: {e}")
        return None

    def hook_interim_assistant(ctx: Dict[str, Any]) -> None:
        """PostLLMCall: LLM 返回后, 把中间文本回调给前端 (interim_assistant_callback)

        W4-17 新增: 把原循环内联 5 行挪到这里, 循环不再关心"流式中间输出怎么发"
        """
        cb = ctx.get("interim_assistant_callback")
        content = ctx.get("llm_content")
        if cb is None or not content:
            return None
        try:
            cb(content)
        except Exception as e:
            logger.warning(f"interim_assistant_callback 执行失败: {e}")
        return None

    def hook_audit_tool_use(ctx: Dict[str, Any]) -> None:
        """PostToolUse: 把工具调用写到结构化审计日志

        W4-17 新增: 给 ops 团队用的工具调用审计, JSONL 格式, 写到 AUDIT_LOG_PATH
        (默认 backend/data/audit/tool_audit.jsonl, 测试时可换)
        失败不抛: 审计失败不能影响主流程
        """
        path = ctx.get("audit_log_path")
        if path is None:
            # 默认路径, 但要避免在测试 / 无盘环境下炸
            try:
                from pathlib import Path
                default = Path("backend/data/audit/tool_audit.jsonl")
                if not default.parent.exists():
                    return None
                path = str(default)
            except Exception:
                return None
        import json as _json
        try:
            record = {
                "ts": _time(),
                "session_id": ctx.get("session_id"),
                "tool": ctx.get("tool_name"),
                "args_keys": sorted(list((ctx.get("arguments") or {}).keys())),
                "is_error": ctx.get("is_error", False),
                "elapsed": round(ctx.get("elapsed", 0.0), 3),
                "tool_call_id": ctx.get("tool_call_id"),
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"audit log write failed: {e}")
        return None

    def hook_tool_stats(ctx: Dict[str, Any]) -> None:
        """PostToolUse: 累积工具调用统计 (调用次数 / 错误次数 / 累计耗时)

        W4-17 新增: 简单 dict 计数, 暴露给监控 / 调试
        ctx["tool_stats"] 是个 dict, hook 写入; 调用方读 ctx["tool_stats"]
        """
        stats = ctx.get("tool_stats")
        if stats is None:
            return None
        name = ctx.get("tool_name", "unknown")
        is_error = ctx.get("is_error", False)
        elapsed = float(ctx.get("elapsed", 0.0) or 0.0)
        entry = stats.setdefault(name, {"calls": 0, "errors": 0, "total_elapsed": 0.0})
        entry["calls"] += 1
        entry["total_elapsed"] += elapsed
        if is_error:
            entry["errors"] += 1
        return None

    register_hook("UserPromptSubmit", hook_step_callback)
    register_hook("PostLLMCall", hook_interim_assistant)
    register_hook("PreToolUse", hook_track_tool_used)
    register_hook("PostToolUse", hook_post_tool_side_effects)
    register_hook("PostToolUse", hook_audit_tool_use)
    register_hook("PostToolUse", hook_tool_stats)
    register_hook("Stop", hook_memory_save)
    logger.info("default agent hooks registered (6 events, 7 hooks)")
