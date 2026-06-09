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

⚠️ W1-3 必修（2026-06-07）：接 AsyncSqliteSaver 给 langchain 路径持久化 state
  - 自研 agent.py: 不用 checkpoint (不持久化)
  - langchain_agent.py: 下面 _make_checkpointer() 工厂 + astream_events config 加
    thread_id。W1-3 验证: session 改同 thread_id 重启能续上历史。
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from app.core.base import Message
from app.core.langchain_callbacks import SSEStreamCallback
from app.llm.langchain_adapter import TongYongLLMAdapter
from app.tools.langchain_adapter import registry_to_langchain_tools
from app.tools.registry import registry as _tool_registry


# ─────────────────────────────────────────────────────────
# Checkpointer 工厂 (W1-3)
# ─────────────────────────────────────────────────────────

_CHECKPOINTER_PATH = Path(__file__).parent.parent / "data" / "lg_checkpoint.sqlite"
_CHECKPOINTER_PATH.parent.mkdir(parents=True, exist_ok=True)


def _use_checkpointer():
    """返 AsyncSqliteSaver 的 asynccontextmanager (CM)

    ⚠️ AsyncSqliteSaver.from_conn_string 是 @asynccontextmanager
    必须用 await + __aenter__ 拿实例, 不能 await 这个函数本身。

    用法:
        cm = _use_checkpointer()
        cp = await cm.__aenter__()
        try:
            ...
        finally:
            await cm.__aexit__(None, None, None)
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    return AsyncSqliteSaver.from_conn_string(str(_CHECKPOINTER_PATH))

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
    # 必修 1+2 合并（2026-06-07 W1-3 修）：
    #   之前 if session_id 走 _init_session, else 走 3 件 — _init_session 不存在
    #   现在统一走 3 件 (base + memory + domain), session_id 存在时
    #   domain 会按 session 选; 不存在时用 "default" 做兜底。
    if session_id:
        yield _progress(f"加载 session {session_id[:8]}...")
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
    yield _progress("上下文装配完成")

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
            m for m in agent_engine.context.messages if m.role == "system"
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

    # ── 滑动窗口截断：保留首 2 条（开场语境）+ 末 20 条（最近对话） ──
    # 触发场景：minimaxi.com 等短窗口 provider 在历史累计 60 条 messages 时
    # 会返回 400 "context window exceeds limit (2013)"，把整轮 agent 调用打挂、
    # SSE 流只 yield done、前端看到空白响应。截断后老 session 也能继续走通。
    # 阈值取保守值 22（首2+末20），给 system prompt + 当前 user 消息留余量。
    KEEP_HEAD = 2
    KEEP_TAIL = 20
    if len(chat_history) > KEEP_HEAD + KEEP_TAIL:
        dropped = len(chat_history) - KEEP_HEAD - KEEP_TAIL
        logger.info(
            f"[langchain] 截断 chat_history: {len(chat_history)} 条 → "
            f"首 {KEEP_HEAD} + 末 {KEEP_TAIL}（丢弃中间 {dropped} 条）"
        )
        chat_history = chat_history[:KEEP_HEAD] + chat_history[-KEEP_TAIL:]

    # ── 3. 创建 ReAct Agent (带 checkpointer) ──────────
    max_iterations = 20
    if hasattr(agent_engine, 'budget'):
        max_iterations = agent_engine.budget.max_rounds

    # W1-3: 接 AsyncSqliteSaver, session_id 当 thread_id
    # session_id=None 时, 不用 checkpointer (ephemeral 不污染持久化)
    thread_id = session_id or f"ephemeral-{_time.time()}"
    is_persistent = bool(session_id)

    if is_persistent:
        checkpointer_cm = _use_checkpointer()
        checkpointer = await checkpointer_cm.__aenter__()
        try:
            agent = create_react_agent(
                model=lc_llm,
                tools=lc_tools,
                prompt=system_prompt,
                checkpointer=checkpointer,
                debug=True,
            )
        except Exception:
            await checkpointer_cm.__aexit__(None, None, None)
            checkpointer_cm = None
            raise
    else:
        checkpointer = None
        checkpointer_cm = None
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

        # W1-3: astream_events config 加 thread_id, 接上 checkpointer
        #   - recursion_limit: 每轮 LLM + Tool 两步
        #   - configurable.thread_id: session_id 决定持久化 key
        #   - callbacks: SSE 推流
        astream_config: dict = {
            "callbacks": [callback],
            "recursion_limit": max_iterations * 2,
        }
        if is_persistent:
            astream_config["configurable"] = {"thread_id": thread_id}

        # 使用 astream_events 获取流式事件
        # W2-2: 切 thinking (Q1/Q2 必修 — LLM 输出 <think>...</think> 段)
        #  state machine: 4 状态
        #  - NORMAL: 普通内容
        #  - IN_THINK: <think> 内部
        #  - THINK_DONE_PENDING: 等 </think> 关闭后推 done
        # 策略: 跟 on_chat_model_stream 同步, 边收边切
        import re
        THINK_OPEN = re.compile(r"<think>")
        THINK_CLOSE = re.compile(r"</think>")
        think_buf = ""
        text_buf = ""
        in_think = False
        cumulative_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        async for event in agent.astream_events(  # type: ignore[call-overload]
            input={"messages": input_messages},
            config=astream_config,  # type: ignore[arg-type]
            version="v2",
        ):
            kind = event.get("event", "")

            # LLM 生成的 token（流式模式）— W2-2 切 thinking
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    text = chunk.content
                    # usage 也可能挂在 chunk 上 (v2 走 message_metadata)
                    if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                        for k, v in chunk.usage_metadata.items():
                            cumulative_usage[k] = cumulative_usage.get(k, 0) + (v or 0)
                    # 切 thinking/text
                    pos = 0
                    while pos < len(text):
                        if not in_think:
                            m = THINK_OPEN.search(text, pos)
                            if m:
                                if m.start() > pos:
                                    yield _content(text[pos:m.start()])
                                pos = m.end()
                                in_think = True
                            else:
                                yield _content(text[pos:])
                                pos = len(text)
                        else:
                            m = THINK_CLOSE.search(text, pos)
                            if m:
                                if m.start() > pos:
                                    yield {
                                        "type": "thinking_delta",
                                        "content": text[pos:m.start()],
                                        "timestamp": _time.time(),
                                    }
                                pos = m.end()
                                in_think = False
                                yield {
                                    "type": "thinking_done",
                                    "timestamp": _time.time(),
                                }
                            else:
                                yield {
                                    "type": "thinking_delta",
                                    "content": text[pos:],
                                    "timestamp": _time.time(),
                                }
                                pos = len(text)

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
                                # 收 usage_metadata (W2-2 — 全在 AIMessage 上)
                                if hasattr(last, "usage_metadata") and last.usage_metadata:
                                    for k, v in last.usage_metadata.items():
                                        cumulative_usage[k] = cumulative_usage.get(k, 0) + (v or 0)
                                is_ai = True
                    elif isinstance(output, AIMessage):
                        text = output.content
                        if hasattr(output, "usage_metadata") and output.usage_metadata:
                            for k, v in output.usage_metadata.items():
                                cumulative_usage[k] = cumulative_usage.get(k, 0) + (v or 0)
                        is_ai = True
                    # 只提取 AIMessage 内容，跳过 ToolMessage 等；去重
                    if is_ai and text and text != last_yielded_text:
                        should_yield = had_tool_call or not collected_content
                        if should_yield:
                            last_yielded_text = text
                            collected_content.append(text)
                            # W2-2: 切 <think>...</think>
                            #   非流式 LLM (TongYongLLMAdapter._agenerate) 走 on_chain_end
                            #   完整 text 一次性给 — 用 regex 切
                            THINK_OPEN_RE = re.compile(r"<think>")
                            THINK_CLOSE_RE = re.compile(r"</think>")
                            parts = []
                            pos = 0
                            while pos < len(text):
                                m_open = THINK_OPEN_RE.search(text, pos)
                                if not m_open:
                                    parts.append(("text", text[pos:]))
                                    break
                                if m_open.start() > pos:
                                    parts.append(("text", text[pos:m_open.start()]))
                                m_close = THINK_CLOSE_RE.search(text, m_open.end())
                                if not m_close:
                                    # 没关闭 — 整段算 think
                                    parts.append(("think", text[m_open.end():]))
                                    break
                                parts.append(("think", text[m_open.end():m_close.start()]))
                                pos = m_close.end()
                            for ptype, ptext in parts:
                                if ptype == "text" and ptext:
                                    yield _content(ptext)
                                elif ptype == "think" and ptext:
                                    yield {
                                        "type": "thinking_delta",
                                        "content": ptext,
                                        "timestamp": _time.time(),
                                    }
                            if any(ptype == "think" for ptype, _ in parts):
                                yield {
                                    "type": "thinking_done",
                                    "timestamp": _time.time(),
                                }

            # 工具完成
            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output = event.get("data", {}).get("output", "")
                emoji = _get_emoji(tool_name)
                preview = str(output).strip()[:120].replace("\n", " ")
                if len(str(output).strip()) > 120:
                    preview += "..."
                is_error = str(output).startswith("工具执行失败") if output else False
                # W2-3: 工具异常推 tool_error (而非 tool_complete, 跟 stream.py 收 11 类对齐)
                if is_error:
                    yield {
                        "type": "tool_error",
                        "tool_name": tool_name,
                        "result_preview": preview,
                        "error": str(output)[:500],
                        "emoji": emoji,
                        "timestamp": _time.time(),
                    }
                else:
                    yield {
                        "type": "tool_complete",
                        "tool_name": tool_name,
                        "result_preview": preview,
                        "duration": 0,
                        "error": False,
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

    # W2-3: 推 context 事件 (上下文容量 — stream.py 收 "context" 事件)
    #   schema: {"context": {"message_count": N, "threshold": T, ...}}
    msg_count = len(ctx.messages) if hasattr(ctx, "messages") else 0
    yield {
        "type": "context",
        "context": {
            "message_count": msg_count,
            "threshold": 10,
        },
        "timestamp": _time.time(),
    }

    # W2-3: 推 budget_warning 事件 (IterationBudget 共享)
    #   schema: {"content": "已用 N/50 轮"} (stream.py 收的是 content 字符串)
    budget = getattr(agent_engine, "budget", None)
    if budget is not None:
        current = getattr(budget, "current_round", 0)
        max_rounds = getattr(budget, "max_rounds", 50)
        yield {
            "type": "budget_warning",
            "content": f"已用 {current}/{max_rounds} 轮 (current_round={current}, max_rounds={max_rounds})",
            "timestamp": _time.time(),
        }

    # W2-2: 推 usage (token 用量 — stream.py 收 "usage" 事件)
    #   schema: {"usage": {input/output/total_tokens}, "round": N, "cumulative": {...}}
    if cumulative_usage and cumulative_usage.get("total_tokens", 0) > 0:
        yield {
            "type": "usage",
            "usage": cumulative_usage,
            "round": getattr(agent_engine.budget, "current_round", 0)
                if getattr(agent_engine, "budget", None) else 0,
            "cumulative": cumulative_usage,
            "timestamp": _time.time(),
        }

    yield _done(session_id or "", tools_used, commands_executed)


def _get_emoji(tool_name: str) -> str:
    """获取工具 emoji"""
    entry = _tool_registry.get_entry(tool_name)
    return entry.emoji if entry else "🔧"
