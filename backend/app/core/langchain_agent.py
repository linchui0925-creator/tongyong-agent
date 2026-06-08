"""
LangChain ReAct Agent — 替代 agent.py 中手写 ReAct 循环

使用 LangGraph 的 create_react_agent 实现：
- LLM 自主决定调用什么工具
- 自动处理工具结果反馈
- 通过 Callbacks 实现 SSE 流式输出
- 支持预算控制、上下文压缩等现有功能

用法：
    from app.core.langchain_agent import stream_chat_langchain
    async for event in stream_chat_langchain(agent_engine, session_id, message, ...):
        yield event
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from app.core.base import Message
from app.core.langchain_callbacks import SSEStreamCallback
from app.llm.langchain_adapter import TongYongLLMAdapter
from app.tools.langchain_adapter import registry_to_langchain_tools
from app.tools.registry import registry as _tool_registry

logger = logging.getLogger(__name__)


async def stream_chat_langchain(
    agent_engine,
    session_id: Optional[str],
    message: str,
    use_memory: bool = True,
    step_callback: Optional[callable] = None,
    interim_assistant_callback: Optional[callable] = None,
    memory_manager: Optional[Any] = None,
    prompt_caching: bool = False,
    clarify_question_id: Optional[str] = None,
    clarify_answer: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    使用 LangGraph ReAct Agent 的流式聊天。

    与 agent_engine.stream_chat() 接口兼容，yield 相同格式的 SSE 事件。
    """
    import time as _time
    start_time = _time.time()

    def _progress(text: str):
        return {"type": "progress", "content": text, "timestamp": _time.time()}

    def _content(chunk: str):
        return {"type": "content", "content": chunk, "timestamp": _time.time()}

    def _done(session_id: str = "", tools_used: List[str] = None, commands_executed: List[str] = None):
        return {
            "type": "done",
            "session_id": session_id,
            "tools_used": tools_used or [],
            "commands_executed": commands_executed or [],
            "processing_time": round(_time.time() - start_time, 2),
            "usage": {},
            "timestamp": _time.time(),
        }

    yield _progress("正在初始化...")

    # ── 1. 加载上下文和记忆 ─────────────────────────────
    ctx = agent_engine.context
    if session_id:
        yield _progress("加载身份认知...")
        agent_engine._init_session(session_id)
    else:
        # 必修 1 配套：旧代码只在 session_id 存在时调 _inject_base_system_prompt，
        # 但新 session 也要带身份认知（跟 agent.chat() / stream_chat 一致）。
        # 跟 agent.py line 290-292 保持一致：base + memory + domain 三件必调。
        try:
            agent_engine._inject_base_system_prompt()
        except Exception as e:
            logger.warning(f"[langchain] 注入 base system prompt 失败: {e}")
        try:
            await agent_engine._inject_memory(session_id or "default")
        except Exception as e:
            logger.warning(f"[langchain] 注入 memory 失败: {e}")
        try:
            await agent_engine._ensure_domain_prompts(session_id or "default")
        except Exception as e:
            logger.warning(f"[langchain] 注入 domain 失败: {e}")
        yield _progress("加载历史对话...")

    # 添加用户消息
    ctx.add_message("user", message)

    # ── 2. 构建 LangChain 组件 ─────────────────────────
    yield _progress("正在思考...")

    # LLM 适配器
    lc_llm = TongYongLLMAdapter(agent_engine.llm)

    # Tool 适配器
    lc_tools = registry_to_langchain_tools()

    # 构建 system prompt
    # ⚠️ 必修 1 修复（2026-06-07）：
    # 旧代码用 hasattr(agent_engine, '_build_system_prompt')，但 agent.py 实际方法
    # 叫 _inject_base_system_prompt()，导致 hasattr 永远 False → system_prompt 永远
    # 落到 fallback "你是一个有用的 AI 助手"，use_langchain=true 走的是降级路径。
    # 修法：复用 stream_chat 的 ctx 装配（_inject_base_system_prompt() 已经在
    # agent_engine.ctx 里注入了 system prompt），直接读第一条 system message。
    system_prompt = ""
    try:
        ctx_system_msgs = [
            m for m in agent_engine.ctx.messages if m.role == "system"
        ]
        if ctx_system_msgs:
            system_prompt = "\n\n".join(
                m.content for m in ctx_system_msgs if m.content
            )
    except Exception as e:
        logger.warning(f"[langchain] 读 ctx system prompt 失败: {e}")

    if not system_prompt:
        system_prompt = "你是一个有用的 AI 助手，可以使用工具来完成任务。"

    # 构建 chat history（从 context 转换）
    chat_history = []
    for msg in ctx.get_messages()[:-1]:  # 排除最后一条 user 消息
        if msg.role == "system":
            chat_history.append(SystemMessage(content=msg.content or ""))
        elif msg.role == "user":
            chat_history.append(HumanMessage(content=msg.content or ""))
        elif msg.role == "assistant":
            chat_history.append(AIMessage(content=msg.content or ""))

    # ── 3. 创建 ReAct Agent ───────────────────────────
    max_iterations = 20
    if hasattr(agent_engine, 'budget'):
        max_iterations = agent_engine.budget.max_rounds

    agent = create_react_agent(
        model=lc_llm,
        tools=lc_tools,
        prompt=system_prompt,
        debug=True,
    )

    # ── 4. 通过 Callbacks 流式执行 ─────────────────────
    collected_content = []
    tools_used = []
    commands_executed = []
    had_tool_call = False
    last_yielded_text = None

    async def _yield_event(event: dict):
        """收集事件并记录内容"""
        event_type = event.get("type", "")
        if event_type == "content":
            collected_content.append(event.get("content", ""))
        elif event_type == "tool_start":
            tool_name = event.get("tool_name", "")
            if tool_name not in tools_used:
                tools_used.append(tool_name)
            if tool_name == "terminal":
                cmd = event.get("arguments", {}).get("command", "")
                if cmd:
                    commands_executed.append(cmd)

    callback = SSEStreamCallback(yield_fn=_yield_event)

    # 执行 agent
    try:
        # 构建输入
        input_messages = chat_history + [HumanMessage(content=message)]

        # 使用 astream_events 获取流式事件
        async for event in agent.astream_events(
            {"messages": input_messages},
            config={
                "callbacks": [callback],
                "recursion_limit": max_iterations * 2,  # 每轮有 LLM + Tool 两步
            },
            version="v2",
        ):
            kind = event.get("event", "")

            # LLM 生成的 token（流式模式）
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _content(chunk.content)

            # 工具开始
            elif kind == "on_tool_start":
                had_tool_call = True
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                emoji = _get_emoji(tool_name)
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                if tool_name == "terminal":
                    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
                    if cmd:
                        commands_executed.append(cmd)
                yield {
                    "type": "tool_start",
                    "tool_name": tool_name,
                    "arguments": tool_input if isinstance(tool_input, dict) else {},
                    "emoji": emoji,
                    "timestamp": _time.time(),
                }

            # chain 结束（可能包含最终输出 — 非流式 LLM 走这里）
            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if output:
                    text = None
                    is_ai = False
                    if isinstance(output, dict) and "messages" in output:
                        msgs = output["messages"]
                        if msgs:
                            last = msgs[-1]
                            if isinstance(last, AIMessage):
                                text = getattr(last, "content", None)
                                is_ai = True
                    elif isinstance(output, AIMessage):
                        text = output.content
                        is_ai = True
                    # 只提取 AIMessage 内容，跳过 ToolMessage 等；去重
                    if is_ai and text and text != last_yielded_text:
                        should_yield = had_tool_call or not collected_content
                        if should_yield:
                            last_yielded_text = text
                            collected_content.append(text)
                            yield _content(text)

            # 工具完成
            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output = event.get("data", {}).get("output", "")
                emoji = _get_emoji(tool_name)
                preview = str(output).strip()[:120].replace("\n", " ")
                if len(str(output).strip()) > 120:
                    preview += "..."
                is_error = str(output).startswith("工具执行失败") if output else False
                yield {
                    "type": "tool_complete",
                    "tool_name": tool_name,
                    "result_preview": preview,
                    "duration": 0,
                    "error": is_error,
                    "emoji": emoji,
                    "timestamp": _time.time(),
                }

        # 推送最终内容（如果 astream_events 没有推送完整内容）
        # Agent 的最终输出在 messages 的最后一条
        # collected_content 已经通过事件收集

    except Exception as e:
        logger.error(f"LangChain Agent 执行失败: {e}", exc_info=True)
        yield {"type": "error", "error": str(e), "timestamp": _time.time()}
        yield _done(session_id or "", tools_used, commands_executed)
        return

    # ── 5. 完成 ──────────────────────────────────────
    # 记录到 context
    full_text = "".join(collected_content)
    if full_text:
        ctx.add_message("assistant", full_text)

    yield _done(session_id or "", tools_used, commands_executed)


def _get_emoji(tool_name: str) -> str:
    """获取工具 emoji"""
    entry = _tool_registry.get_entry(tool_name)
    return entry.emoji if entry else "🔧"
