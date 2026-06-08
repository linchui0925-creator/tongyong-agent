"""
流式聊天API路由模块
提供SSE流式输出功能，支持实时对话
"""
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import asyncio
import json
import os
import time
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


# W3 切流量: 灰度百分比, ENV 控制
#   LANGCHAIN_ROLLOUT=100 → 100% (默认, 全量)
#   LANGCHAIN_ROLLOUT=50  → 50% (灰度)
#   LANGCHAIN_ROLLOUT=0   → 0% (回滚到自研)
LANGCHAIN_ROLLOUT_PCT = int(os.getenv("LANGCHAIN_ROLLOUT", "100"))


def _should_use_langchain(
    request_use_langchain: bool,
    session_id: Optional[str],
    override: Optional[bool],
) -> bool:
    """
    决定本轮是否走 LangChain 路径

    决策顺序 (行为验证优先: 显式 > 默认 > 灰度):
      1. override=True  → 永远走 langchain (测试/排障)
      2. override=False → 永远走自研 (回滚兜底)
      3. request=False  → 走自研 (客户端显式不要)
      4. request=True   → 走灰度决策 (hash(session_id) % 100 < rollout_pct)
    """
    if override is True:
        return True
    if override is False:
        return False
    if not request_use_langchain:
        return False
    # request_use_langchain=True → 走灰度
    # session_id 缺失时, 退化为全开 (单次调用不卡灰度, 让无 session 客户端走默认)
    if not session_id:
        return True
    if LANGCHAIN_ROLLOUT_PCT >= 100:
        return True
    if LANGCHAIN_ROLLOUT_PCT <= 0:
        return False
    return hash(session_id) % 100 < LANGCHAIN_ROLLOUT_PCT


class StreamChatRequest(BaseModel):
    """流式聊天请求模型"""
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[str] = Field(None)
    use_memory: bool = Field(True)
    use_langchain: bool = Field(True, description="使用 LangChain ReAct Agent (W3 默认开)")

    # W3 切流量: 灰度开关, ENV 控制百分比
    #   LANGCHAIN_ROLLOUT=100 → 100% (默认, 全量)
    #   LANGCHAIN_ROLLOUT=50  → 50% (灰度)
    #   LANGCHAIN_ROLLOUT=0   → 0% (回滚)
    langchain_rollout_override: Optional[bool] = Field(
        None, description="强制覆盖 (测试/排障用, 不受灰度影响)"
    )
    # clarify 恢复参数
    clarify_question_id: Optional[str] = Field(None)
    clarify_answer: Optional[str] = Field(None)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('消息内容不能为空')
        return v.strip()


async def generate_stream_response(
    message: str,
    session_id: Optional[str] = None,
    use_memory: bool = True,
    clarify_question_id: Optional[str] = None,
    clarify_answer: Optional[str] = None,
    use_langchain: bool = False,
    langchain_rollout_override: Optional[bool] = None,
):
    """
    生成流式响应

    接收 agent.stream_chat() 的 dict yields，转换为 SSE 事件：
    - {"type": "progress", ...} → event: progress
    - {"type": "content", ...}  → event: content
    - {"type": "done", ...}     → event: done
    """
    try:
        from app.main import agent_engine
        if agent_engine is None:
            yield {
                "event": "error",
                "data": json.dumps({
                    "type": "error",
                    "message": "Agent引擎未初始化",
                    "code": "ENGINE_NOT_INITIALIZED"
                })
            }
            return

        # W3 切流量: 决策是否走 langchain (显式 > 默认 > 灰度)
        effective_use_langchain = _should_use_langchain(
            request_use_langchain=use_langchain,
            session_id=session_id,
            override=langchain_rollout_override,
        )
        logger.info(
            f"开始流式聊天: session={session_id}, "
            f"request_use_langchain={use_langchain}, "
            f"override={langchain_rollout_override}, "
            f"rollout_pct={LANGCHAIN_ROLLOUT_PCT}, "
            f"effective={effective_use_langchain}"
        )

        yield {
            "event": "start",
            "data": json.dumps({"type": "start", "timestamp": time.time()})
        }

        # 选择 agent 实现
        if effective_use_langchain:
            from app.core.langchain_agent import stream_chat_langchain
            agent_stream = stream_chat_langchain(
                agent_engine=agent_engine,
                session_id=session_id,
                message=message,
                use_memory=use_memory,
                clarify_question_id=clarify_question_id,
                clarify_answer=clarify_answer,
            )
        else:
            agent_stream = agent_engine.stream_chat(
                session_id=session_id,
                message=message,
                use_memory=use_memory,
                clarify_question_id=clarify_question_id,
                clarify_answer=clarify_answer,
            )

        full_response = ""
        try:
            async for item in agent_stream:
                # 兼容旧的纯字符串 yield
                if isinstance(item, str):
                    full_response += item
                    yield {
                        "event": "content",
                        "data": json.dumps({
                            "type": "content",
                            "content": item,
                            "full_content": full_response,
                            "timestamp": time.time()
                        })
                    }
                    continue

                event_type = item.get("type", "content")

                if event_type == "progress":
                    yield {
                        "event": "progress",
                        "data": json.dumps({
                            "type": "progress",
                            "content": item.get("content", ""),
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type in ("tool_start", "tool_complete", "tool_error"):
                    yield {
                        "event": event_type,
                        "data": json.dumps(item)
                    }

                elif event_type == "thinking_delta":
                    yield {
                        "event": "thinking_delta",
                        "data": json.dumps({
                            "type": "thinking_delta",
                            "content": item.get("content", ""),
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type == "thinking_done":
                    yield {
                        "event": "thinking_done",
                        "data": json.dumps({
                            "type": "thinking_done",
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type == "tool_feedback":
                    yield {
                        "event": "tool_feedback",
                        "data": json.dumps({
                            "type": "tool_feedback",
                            "content": item.get("content", ""),
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type == "ask":
                    yield {
                        "event": "ask",
                        "data": json.dumps({
                            "type": "ask",
                            "question": item.get("question", ""),
                            "choices": item.get("choices", []),
                            "question_id": item.get("question_id", ""),
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type == "budget_warning":
                    yield {
                        "event": "budget_warning",
                        "data": json.dumps({
                            "type": "budget_warning",
                            "content": item.get("content", ""),
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type == "usage":
                    # 实时 token 用量 — 每轮 LLM 调用后立刻推，不等 done
                    yield {
                        "event": "usage",
                        "data": json.dumps({
                            "type": "usage",
                            "usage": item.get("usage", {}),
                            "round": item.get("round", 0),
                            "cumulative": item.get("cumulative", {}),
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type == "context":
                    # 上下文容量快照 — TokenUsageBar 用
                    yield {
                        "event": "context",
                        "data": json.dumps({
                            "type": "context",
                            "context": item.get("context", {}),
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type == "content":
                    chunk = item.get("content", "")
                    full_response += chunk
                    yield {
                        "event": "content",
                        "data": json.dumps({
                            "type": "content",
                            "content": chunk,
                            "full_content": full_response,
                            "timestamp": time.time()
                        })
                    }

                elif event_type == "done":
                    # Include usage if present
                    done_data = {
                        "type": "done",
                        "session_id": item.get("session_id", session_id or ""),
                        "tools_used": item.get("tools_used", []),
                        "commands_executed": item.get("commands_executed", []),
                        "processing_time": item.get("processing_time", 0),
                        "usage": item.get("usage", {}),
                        "timestamp": time.time()
                    }
                    yield {
                        "event": "done",
                        "data": json.dumps(done_data)
                    }

        except Exception as e:
            logger.error(f"流式处理错误: {e}")
            yield {
                "event": "error",
                "data": json.dumps({
                    "type": "error",
                    "message": str(e),
                    "code": "STREAM_ERROR"
                })
            }
            return

        logger.info(f"流式聊天完成，响应长度: {len(full_response)}")

    except Exception as e:
        logger.error(f"流式聊天错误: {e}", exc_info=True)
        yield {
            "event": "error",
            "data": json.dumps({
                "type": "error",
                "message": str(e),
                "code": "INTERNAL_ERROR"
            })
        }


@router.post("/stream")
async def stream_chat(request: StreamChatRequest):
    """
    流式聊天接口
    
    使用Server-Sent Events (SSE) 实现实时流式输出
    
    Args:
        request: 流式聊天请求
        
    Returns:
        StreamingResponse: SSE流式响应
    """
    return EventSourceResponse(
        generate_stream_response(
            message=request.message,
            session_id=request.session_id,
            use_memory=request.use_memory,
            use_langchain=request.use_langchain,
            langchain_rollout_override=request.langchain_rollout_override,
            clarify_question_id=request.clarify_question_id,
            clarify_answer=request.clarify_answer,
        )
    )


@router.get("/stream/test")
async def test_stream():
    """测试流式输出端点"""
    async def test_generator():
        for i in range(10):
            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "test",
                    "message": f"测试消息 {i+1}",
                    "timestamp": time.time()
                })
            }
            await asyncio.sleep(0.1)
        
        yield {
            "event": "done",
            "data": json.dumps({
                "type": "done",
                "timestamp": time.time()
            })
        }
    
    return EventSourceResponse(test_generator())


class ClarifyRequest(BaseModel):
    """clarify 回答请求模型"""
    question_id: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    session_id: Optional[str] = Field(None)


@router.post("/clarify")
async def submit_clarify_answer(request: ClarifyRequest):
    """
    用户提交 clarify 问题的回答。

    前端在用户选择/输入回答后调用此接口，
    然后重新发起 /stream 请求并携带 clarify_question_id 和 clarify_answer 参数。
    """
    try:
        from app.main import agent_engine
        if agent_engine is None:
            return {"success": False, "error": "Agent引擎未初始化"}

        success = agent_engine.set_ask_response(
            question_id=request.question_id,
            answer=request.answer,
        )
        if success:
            logger.info(f"[clarify] 收到回答: question_id={request.question_id}, answer={request.answer[:50]}")
            return {"success": True}
        else:
            return {"success": False, "error": "问题已过期或不存在"}
    except Exception as e:
        logger.error(f"[clarify] 错误: {e}")
        return {"success": False, "error": str(e)}


# ── 主动上下文压缩（前端 TokenUsageBar 触发）──────────────────────────
# 与 stream_chat 内部的 preflight 压缩共用 ContextCompressor，但这条路径：
#   · 不依赖 self.context（避免和正在进行的流式对话抢占）
#   · 直接操作 memory_storage 持久化层（写回后会持久化到 DB）
#   · 用户主动选择时机，不强制


class CompressRequest(BaseModel):
    """主动压缩请求"""
    session_id: str = Field(..., min_length=1)
    # 可选：force=true 即便未达阈值也压缩（默认 false 尊重 should_compress）
    force: bool = Field(False)


@router.post("/compress")
async def compress_session(request: CompressRequest):
    """
    用户主动触发的上下文压缩。

    前端 TokenUsageBar 的"压缩"按钮调用，调 ContextCompressor.compress()
    对 session 历史消息做 LLM summarization，写回 memory_storage。

    返回 {success, before/after tokens, saved_pct, summary, skipped}，
    前端用 before/after 刷新 TokenUsageBar 的百分比显示。
    """
    try:
        from app.main import agent_engine
        if agent_engine is None:
            return {"success": False, "error": "Agent引擎未初始化"}

        result = await agent_engine.compress_session_history(request.session_id)
        if request.force and result.get("skipped"):
            # force 模式：跳过 should_compress 检查，直接压
            messages = await agent_engine.memory_storage.get_messages(request.session_id)
            if not messages:
                return {"success": True, "session_id": request.session_id,
                        "before_messages": 0, "after_messages": 0,
                        "before_tokens": 0, "after_tokens": 0, "saved_pct": 0.0,
                        "summary": "", "forced": True}
            before_chars = sum(len(m.content or "") for m in messages)
            before_tokens = int(before_chars * 0.25)
            compressed, summary_text = await agent_engine.context_compressor.compress(
                messages, agent_engine.llm
            )
            after_chars = sum(len(m.content or "") for m in compressed)
            after_tokens = int(after_chars * 0.25)
            saved_pct = round((before_chars - after_chars) / before_chars * 100, 1) if before_chars else 0.0
            await agent_engine.memory_storage.clear_messages(request.session_id)
            for m in compressed:
                await agent_engine.memory_storage.add_message(request.session_id, m.role, m.content)
            if agent_engine.context.messages:
                agent_engine.context.clear()
            result = {
                "success": True, "session_id": request.session_id,
                "before_messages": len(messages), "after_messages": len(compressed),
                "before_tokens": before_tokens, "after_tokens": after_tokens,
                "saved_pct": saved_pct, "summary": summary_text[:200], "forced": True,
            }
        return result
    except Exception as e:
        logger.error(f"[compress] 错误: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.get("/context-stats/{session_id}")
async def get_context_stats(session_id: str):
    """读 session 当前 context 容量（前端启动 / 切 session 时用来初始化 TokenUsageBar）。"""
    try:
        from app.main import agent_engine
        if agent_engine is None:
            return {"error": "Agent引擎未初始化"}
        return await agent_engine.get_session_context_stats(session_id)
    except Exception as e:
        logger.error(f"[context-stats] 错误: {e}")
        return {"error": str(e)}
