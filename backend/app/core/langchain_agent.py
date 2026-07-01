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
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from app.core.agent_hooks import trigger_hooks, trigger_hooks_async

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
            "needs_continue": False,
            "stop_reason": "",
            "continue_prompt": "",
            "timestamp": _time.time(),
        }

    def _continue_prompt(reason: str) -> str:
        return (
            "继续上一个任务。先基于当前会话里已经完成的工具结果判断进度，"
            "不要重复已经成功完成的步骤；从未完成的下一步继续执行。"
            f"\n\n中断原因：{reason}"
        )

    yield _progress("正在初始化...")

    # ── 1. 加载上下文和记忆 ─────────────────────────────
    ctx = agent_engine.context
    # 必修 1+2 合并（2026-06-07 W1-3 修）：
    #   之前 if session_id 走 _init_session, else 走 3 件 — _init_session 不存在
    #   现在统一走 3 件 (base + memory + domain), session_id 存在时
    #   domain 会按 session 选; 不存在时用 "default" 做兜底。
    if session_id:
        yield _progress(f"加载 session {session_id[:8]}...")
    # ⚠️ 调用顺序很重要 (W4-8 P0-1 修复 2026-06-21)：
    #   三个 inject 全部用 messages.insert(0, ...)，最后调用的反而排最前。
    #   期望 base_prompt 落在位置 0 (LLM 第一眼看到)，所以 base 必须 **最后** 调。
    #   旧版 (base → memory → domain) 实际让 base 落到最底，与注释相反。
    #   修正后顺序: domain → memory → base, 最终 = [base, USER, MEMORY, domain]
    try:
        await agent_engine._ensure_domain_prompts(session_id or "default")
    except Exception as e:
        logger.warning(f"[langchain] 注入 domain 失败: {e}")
    try:
        await agent_engine._inject_memory(session_id or "default")
    except Exception as e:
        logger.warning(f"[langchain] 注入 memory 失败: {e}")
    try:
        agent_engine._inject_base_system_prompt()
    except Exception as e:
        logger.warning(f"[langchain] 注入 base system prompt 失败: {e}")
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
    # W4-23 P2-3 修复: 跳过 system messages — `prompt=system_prompt` 已经传了,
    # 之前在 chat_history 里再 append 会让每轮累积 2 段 system, 60 轮后 checkpointer
    # 累积 4×60=240 段 system, 触发 minimaxi 短窗口 400
    chat_history = []
    for msg in ctx.get_messages()[:-1]:  # 排除最后一条 user 消息
        if msg.role == "system":
            continue  # system 走 prompt= 参数, 不入 chat_history
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

    # ── 3. 创建 ReAct Agent ──────────
    # W4-23 P2-3：恢复 checkpointer (W3-B 临时回退已修)
    # 根因: chat_history 里追加了 system message + `prompt=` 也传了 system,
    #   每轮累积 2 段 system, 60 轮后 checkpointer 累积 120 段 system,
    #   触发 minimaxi 短窗口 400。
    # 修法: chat_history 跳过 system messages, 改回 is_persistent=True。
    # 收益: 60 条历史连续记忆恢复, 跨请求可重入。
    # 注意: is_persistent 仅在 session_id 不为 None 时启用, ephemeral 仍不污染持久化。
    max_iterations = 20
    if hasattr(agent_engine, 'budget'):
        max_iterations = agent_engine.budget.max_rounds

    # W1-3: 接 AsyncSqliteSaver, session_id 当 thread_id
    # W4-23 P2-3: 改回 is_persistent=True (W3-B 临时回退已修)
    #   - chat_history 已去重 system messages, checkpointer 不再累积
    #   - 60 条历史连续记忆恢复
    # session_id=None 时仍走 ephemeral (不污染持久化)
    thread_id = session_id or f"ephemeral-{_time.time()}"
    is_persistent = session_id is not None

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
    stop_reason = ""
    needs_continue = False

    async def _yield_event(event: dict):
        """收集事件并记录内容"""
        event_type = event.get("type", "")
        if event_type == "content":
            collected_content.append(event.get("content", ""))
        elif event_type == "tool_start":
            tool_name = event.get("tool_name", "")
            tool_args = event.get("arguments", {})
            # W4-17: PreToolUse hook (langchain 路径, callback 内)
            # 同步 trigger: callback 不是 async, 用 sync trigger_hooks
            trigger_hooks("PreToolUse", {
                "tool_name": tool_name,
                "arguments": tool_args,
                "tool_call_id": event.get("tool_call_id", ""),
                "context": ctx,
                "tools_used": tools_used,
                "session_id": session_id,
            })
            if tool_name == "terminal":
                cmd = tool_args.get("command", "")
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
        # W3-B 临时改：ephemeral 路径不传 configurable，避免读 checkpointer 状态

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
                budget = getattr(agent_engine, "budget", None)
                if budget is not None:
                    try:
                        budget.advance()
                    except Exception as budget_err:
                        logger.warning(f"[langchain] budget advance failed: {budget_err}")
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                emoji = _get_emoji(tool_name)
                # W4-17: PreToolUse hook (langchain astream_events 路径)
                trigger_hooks("PreToolUse", {
                    "tool_name": tool_name,
                    "arguments": tool_input if isinstance(tool_input, dict) else {},
                    "tool_call_id": "",
                    "context": ctx,
                    "tools_used": tools_used,
                    "session_id": session_id,
                })
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
        err_text = str(e)
        if e.__class__.__name__ == "GraphRecursionError" or "recursion limit" in err_text.casefold():
            stop_reason = f"长任务达到单次执行上限: {err_text}"
            needs_continue = True
            yield {
                "type": "budget_warning",
                "content": stop_reason,
                "timestamp": _time.time(),
            }
            yield _content("本轮达到单次执行上限，已保留当前进度。可以点击“继续执行”从下一步接着跑。")
            yield {
                "type": "done",
                "session_id": session_id or "",
                "tools_used": tools_used,
                "commands_executed": commands_executed,
                "processing_time": round(_time.time() - start_time, 2),
                "usage": {},
                "needs_continue": True,
                "stop_reason": stop_reason,
                "continue_prompt": _continue_prompt(stop_reason),
                "timestamp": _time.time(),
            }
        else:
            yield {"type": "error", "error": err_text, "timestamp": _time.time()}
            yield _done(session_id or "", tools_used, commands_executed)
        return

    # ── 5. 完成 ──────────────────────────────────────
    # 记录到 context
    full_text = "".join(collected_content)
    # W4-3 修复 2026-06-09: 写库前先清掉 <think>...</think> 思考段
    #   根因: 流式 chunks 拼起来的 full_text 含 think, 之前直接进 ctx + memory_storage,
    #   导致 DB / 切会话拉历史看到 "用户要求用一句话介绍..." 这种 thought 段。
    #   修法: 用同一个正则在写库前切, 跟前端 displayContent.replace 保持一致语义。
    full_text_clean = re.sub(r"<think>[\s\S]*?</think>", "", full_text, flags=re.DOTALL).strip()
    # display_text 是"用户实际看到的回答" — 用于 ctx 内存 + 持久化
    display_text = full_text_clean
    if display_text:
        ctx.add_message("assistant", display_text)

    # ── 5.1 持久化写库 (W4-1 必修 2026-06-09) ────────
    # 之前 langchain 路径不调 memory_storage.add_message，导致切会话拉不到历史。
    # 根因: chat() 路径 (agent.py:445-446) 写了，stream_chat() 自研路径写了，
    #       只有 stream_chat_langchain() 这条路径漏掉 — 跟 chat() 一样补上。
    # session_id 必须非空 — 早期空 session 走 ephemeral，这里也跳过。
    # W4-3: 写库用 display_text (无 think 段), user 消息保留原文 (用户没说 think)。
    # W4-17: Stop hook (langchain 路径)
    if session_id:
        # 把"保存 user/assistant 到 memory_storage"挪到 agent_hooks 注册表
        # 默认 hook (hook_memory_save) 处理; 这里构造一个 fake context 给 hook 用
        _ctx_for_hook = ctx if hasattr(ctx, "get_messages") else None
        try:
            # 注意: langchain 路径没有 self.context, 用 _ctx_for_hook
            await trigger_hooks_async("Stop", {
                "context": _ctx_for_hook,
                "final_response_chunks": [display_text] if display_text else [],
                "tools_used": tools_used,
                "commands_executed": commands_executed,
                "session_id": session_id,
                "message": message,
                "memory_storage": getattr(agent_engine, "memory_storage", None),
                "constraint_engine": getattr(agent_engine, "_constraint_engine", None),
            })
            logger.info(
                f"[langchain] persisted via Stop hook: session={session_id}, "
                f"display_len={len(display_text)} (cleaned from {len(full_text)})"
            )
        except Exception as _persist_err:
            logger.error(f"[langchain] 持久化消息失败: {_persist_err}", exc_info=True)

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

    # W4-4 修复 2026-06-09: DashScope 兼容 API 不返回 usage 字段 (provider feature),
    #   链路里所有 usage_metadata 都是空 dict, 推上去前端就显示 0/0/0。
    # 兜底: 估算 usage (业内常见做法, 1 中文 ≈ 1.5 token, 1 英文 ≈ 0.25 token,
    #   简化: 中文字符数 + 英文单词数 * 1.3)
    if cumulative_usage.get("total_tokens", 0) == 0 and (full_text or message):
        # input: user message 字符; output: assistant 干净文本字符 (W4-3 修复后用 display_text)
        in_chars = len(message) if message else 0
        # W4-3: 用 display_text 估算, 不含 think 段
        out_chars = len(display_text) if display_text else 0
        # 简单估算 (中文占多数, 1 字符 ≈ 1.5 token, 加英文标点 1.0)
        in_tok = max(1, int(in_chars * 1.5))
        out_tok = max(1, int(out_chars * 1.5))
        cumulative_usage = {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
        }
        logger.info(
            f"[W4-4] DashScope 未返回 usage, 按字符数估算: "
            f"in={in_tok} (from {in_chars} chars), "
            f"out={out_tok} (from {out_chars} chars)"
        )

    # W2-2: 推 usage (token 用量 — stream.py 收 "usage" 事件)
    #   schema: {"usage": {input/output/total_tokens}, "round": N, "cumulative": {...}}
    # W4-4 改: 即便是估算值也照推, 前端就能显示数字而非 0/0
    if cumulative_usage and cumulative_usage.get("total_tokens", 0) > 0:
        yield {
            "type": "usage",
            "usage": cumulative_usage,
            "round": getattr(agent_engine.budget, "current_round", 0)
                if getattr(agent_engine, "budget", None) else 0,
            "cumulative": cumulative_usage,
            "timestamp": _time.time(),
        }

    # W4-1 改: done 事件带 usage，前端 done 分支会刷新 TokenUsageBar
    yield {
        "type": "done",
        "session_id": session_id or "",
        "tools_used": tools_used,
        "commands_executed": commands_executed,
        "processing_time": round(_time.time() - start_time, 2),
        "usage": cumulative_usage if cumulative_usage else {},
        "needs_continue": needs_continue,
        "stop_reason": stop_reason,
        "continue_prompt": _continue_prompt(stop_reason) if needs_continue else "",
        "timestamp": _time.time(),
    }


def _get_emoji(tool_name: str) -> str:
    """获取工具 emoji"""
    entry = _tool_registry.get_entry(tool_name)
    return entry.emoji if entry else "🔧"
