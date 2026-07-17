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


class _StreamMetrics:
    """
    W3 切流量埋点 — 每次 /api/chat/stream 调用收集 3 指标:
      - latency_ms: 从 start 到收尾的耗时
      - tool_count:  本轮 tool_start 事件数
      - error_code:  失败时的错误代码 (None=成功)

    输出: 一行 JSON 日志 (logger.info)
    取舍: 不接 prometheus (避免引入新依赖, 行为验证: 纯文本可 grep)
    """

    __slots__ = (
        "session_id",
        "use_langchain",
        "request_flag",
        "override",
        "rollout_pct",
        "t0",
        "tool_count",
        "error_code",
        "error_message",
    )

    def __init__(
        self,
        session_id: Optional[str],
        use_langchain: bool,
        request_flag: bool,
        override: Optional[bool],
        rollout_pct: int,
    ):
        self.session_id = session_id
        self.use_langchain = use_langchain
        self.request_flag = request_flag
        self.override = override
        self.rollout_pct = rollout_pct
        self.t0 = time.time()
        self.tool_count = 0
        self.error_code: Optional[str] = None
        self.error_message: Optional[str] = None

    def _snapshot(self, status: str) -> dict:
        latency_ms = round((time.time() - self.t0) * 1000, 1)
        return {
            "metric": "stream_chat",
            "status": status,
            "session_id": self.session_id,
            "use_langchain": self.use_langchain,
            "request_flag": self.request_flag,
            "override": self.override,
            "rollout_pct": self.rollout_pct,
            "latency_ms": latency_ms,
            "tool_count": self.tool_count,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }

    def log_success(self) -> None:
        """成功收尾: 一行 JSON 进 logger.info (W3-2 切流量监控主信号)"""
        logger.info("[METRICS] " + json.dumps(self._snapshot("success"), ensure_ascii=False))

    def log_error(self, code: str, message: str) -> None:
        """失败收尾: error_code + error_message 进 JSON"""
        self.error_code = code
        self.error_message = message[:200]  # 截断, 避免日志爆
        logger.warning("[METRICS] " + json.dumps(self._snapshot("error"), ensure_ascii=False))


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
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    thinking_mode: Optional[str] = Field(None, description="off/auto/always")
    reasoning_effort: Optional[str] = Field(None, description="low/medium/high")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('消息内容不能为空')
        return v.strip()

    @field_validator("attachment_ids")
    @classmethod
    def validate_attachment_ids(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in v or []:
            attachment_id = str(item).strip()
            if not attachment_id or attachment_id in seen:
                continue
            if len(attachment_id) > 80:
                raise ValueError("附件 ID 过长")
            cleaned.append(attachment_id)
            seen.add(attachment_id)
        return cleaned


def _message_with_attachment_context(message: str, attachment_ids: list[str], model_name: Optional[str] = None) -> str:
    if not attachment_ids:
        return message
    try:
        from app.api.attachments import get_attachments_metadata
        from app.api.attachment_processor import format_attachment_context
        from app.llm.model_metadata import model_supports_vision
        attachments = get_attachments_metadata(attachment_ids)
    except Exception as exc:
        logger.warning("[attachments] 读取附件元数据失败: %s", exc)
        attachments = []
        model_supports_vision = lambda _model_name: False  # type: ignore
    if not attachments:
        return message

    image_count = sum(1 for item in attachments if str(item.get("kind") or "") == "image")
    vision_required = any(bool((item.get("extraction_meta") or {}).get("vision_required")) for item in attachments)
    model_can_see = bool(model_name and model_supports_vision(model_name))

    lines = ["", "", "[用户上传附件]", format_attachment_context(attachments)]
    if image_count:
        lines.append("[附件处理说明] 图片附件已准备好；若模型支持视觉输入，请直接结合图片与正文回答。")
    if vision_required and not model_can_see:
        lines.append("[附件处理说明] 当前模型不支持视觉输入，只能基于 OCR 文本或元数据回答；若要完整理解图片，请切换支持视觉的模型。")
    elif vision_required and model_can_see:
        lines.append("[附件处理说明] 当前模型支持视觉输入，可结合图片内容、OCR 结果与附件摘要综合回答。")
    lines.append("需要更多附件正文时调用 attachment_read；没有 extracted_text 时不要假装读过内容。")
    return message + "\n".join(lines)


async def generate_stream_response(
    message: str,
    session_id: Optional[str] = None,
    use_memory: bool = True,
    clarify_question_id: Optional[str] = None,
    clarify_answer: Optional[str] = None,
    use_langchain: bool = False,
    langchain_rollout_override: Optional[bool] = None,
    attachment_ids: Optional[list[str]] = None,
    thinking_mode: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
):
    """
    生成流式响应

    接收 agent.stream_chat() 的 dict yields，转换为 SSE 事件：
    - {"type": "progress", ...} → event: progress
    - {"type": "content", ...}  → event: content
    - {"type": "done", ...}     → event: done
    """
    # W3-2 埋点: 在 try 外先初始化 (兜底用, 避免 except 报 unbound)
    metrics: Optional["_StreamMetrics"] = None
    prelude_t0 = time.time()
    prelude_marks: dict[str, float] = {}
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

        if not session_id:
            session_id = await agent_engine._get_or_create_session()

        # W3 切流量: 决策是否走 langchain (显式 > 默认 > 灰度)
        effective_use_langchain = _should_use_langchain(
            request_use_langchain=use_langchain,
            session_id=session_id,
            override=langchain_rollout_override,
        )
        # W3-2 埋点: 创建 metrics 收集器 (latency/tool_count/error)
        metrics = _StreamMetrics(
            session_id=session_id,
            use_langchain=effective_use_langchain,
            request_flag=use_langchain,
            override=langchain_rollout_override,
            rollout_pct=LANGCHAIN_ROLLOUT_PCT,
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
        prelude_marks["start_sent"] = time.time()
        # 尽早让前端收到首个可见事件，避免等到上下文整理结束才显示。
        yield {
            "event": "progress",
            "data": json.dumps({
                "type": "progress",
                "content": "正在初始化...",
                "timestamp": time.time(),
            })
        }

        current_model_name = None
        current_provider = None
        api_format = None
        runtime_config = {}
        try:
            from app.services.llm_manager import get_llm_manager
            llm_manager = get_llm_manager()
            runtime_config = llm_manager.get_current_runtime_config()
            current_model_name = runtime_config.get('model')
            current_provider = runtime_config.get('provider')
            api_format = runtime_config.get('api_format')
        except Exception:
            current_model_name = None
            current_provider = None
            api_format = None
        effective_message = _message_with_attachment_context(message, attachment_ids or [], current_model_name)
        first_event_sent = False
        prelude_marks["runtime_ready"] = time.time()
        logger.info("[stream] 当前模型运行时配置: %s", json.dumps({
            "provider": current_provider,
            "model": current_model_name,
            "api_format": api_format,
            "stream_mode": runtime_config.get('stream_mode'),
            "api_base": runtime_config.get('api_base'),
        }, ensure_ascii=False))

        # 选择 agent 实现
        prelude_marks["before_agent_select"] = time.time()
        if effective_use_langchain:
            from app.core.langchain_agent import stream_chat_langchain
            agent_stream = stream_chat_langchain(
                agent_engine=agent_engine,
                session_id=session_id,
                message=effective_message,
                use_memory=use_memory,
                clarify_question_id=clarify_question_id,
                clarify_answer=clarify_answer,
            )
        else:
            agent_stream = agent_engine.stream_chat(
                session_id=session_id,
                message=effective_message,
                use_memory=use_memory,
                clarify_question_id=clarify_question_id,
                clarify_answer=clarify_answer,
            )

        full_response = ""
        prelude_marks["agent_built"] = time.time()
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
                    first_event_sent = True
                    yield {
                        "event": "progress",
                        "data": json.dumps({
                            "type": "progress",
                            "content": item.get("content", ""),
                            "timestamp": item.get("timestamp", time.time())
                        })
                    }

                elif event_type in ("tool_start", "tool_complete", "tool_error"):
                    # W3-2 埋点: tool_count 累加 (tool_start / tool_complete / tool_error 都算调用)
                    if event_type == "tool_start":
                        metrics.tool_count += 1
                    yield {
                        "event": event_type,
                        "data": json.dumps(item)
                    }

                elif event_type == "thinking_delta":
                    first_event_sent = True
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
                    first_event_sent = True
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

                elif event_type == "error":
                    # 透传 agent 内部捕获的错误事件给客户端
                    # (例: stream_chat_langchain 的 except 分支会 yield {type: error, error: ...})
                    err_msg = item.get("error") or item.get("message") or "未知错误"
                    err_code = item.get("code") or "AGENT_ERROR"
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "type": "error",
                            "message": err_msg,
                            "code": err_code,
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
                        "artifact_previews": item.get("artifact_previews", []),
                        "processing_time": item.get("processing_time", 0),
                        "usage": item.get("usage", {}),
                        "needs_continue": item.get("needs_continue", False),
                        "stop_reason": item.get("stop_reason", ""),
                        "continue_prompt": item.get("continue_prompt", ""),
                        "timestamp": time.time()
                    }
                    yield {
                        "event": "done",
                        "data": json.dumps(done_data)
                    }

        except Exception as e:
            logger.error(f"流式处理错误: {e}")
            metrics.log_error("STREAM_ERROR", str(e))
            yield {
                "event": "error",
                "data": json.dumps({
                    "type": "error",
                    "message": str(e),
                    "code": "STREAM_ERROR"
                })
            }
            return

        if not first_event_sent:
            yield {
                "event": "progress",
                "data": json.dumps({
                    "type": "progress",
                    "content": "正在生成回复...",
                    "timestamp": time.time(),
                })
            }
        prelude_marks["first_visible_event"] = time.time()
        logger.info(
            "[stream] prelude_ms=%s",
            json.dumps({
                "total": round((time.time() - prelude_t0) * 1000, 1),
                "start_to_runtime_ready": round((prelude_marks.get("runtime_ready", time.time()) - prelude_t0) * 1000, 1),
                "runtime_ready_to_agent_select": round((prelude_marks.get("before_agent_select", time.time()) - prelude_marks.get("runtime_ready", prelude_t0)) * 1000, 1),
                "agent_build_ms": round((prelude_marks.get("agent_built", time.time()) - prelude_marks.get("before_agent_select", prelude_t0)) * 1000, 1),
                "first_visible_event_ms": round((prelude_marks.get("first_visible_event", time.time()) - prelude_t0) * 1000, 1),
            }, ensure_ascii=False)
        )
        # W3-2 埋点: 成功收尾打 metrics 日志
        metrics.log_success()
        logger.info(f"流式聊天完成，响应长度: {len(full_response)}")

    except Exception as e:
        logger.error(f"流式聊天错误: {e}", exc_info=True)
        # W3-2 埋点: 兜底 INTERNAL_ERROR (metrics 可能在 agent_engine 初始化前未创建)
        if metrics is not None:
            metrics.log_error("INTERNAL_ERROR", str(e))
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
            attachment_ids=request.attachment_ids,
            thinking_mode=request.thinking_mode,
            reasoning_effort=request.reasoning_effort,
        )
    )


@router.get("/stream/test")
async def test_stream():
    """测试流式输出端点"""
    async def test_generator():
        yield {
            "event": "start",
            "data": json.dumps({
                "type": "start",
                "timestamp": time.time(),
            })
        }
        for i in range(10):
            yield {
                "event": "progress",
                "data": json.dumps({
                    "type": "progress",
                    "content": f"测试消息 {i+1}",
                    "timestamp": time.time()
                })
            }
            yield {
                "event": "content",
                "data": json.dumps({
                    "type": "content",
                    "content": f"测试消息 {i+1}",
                    "full_content": f"测试消息 {i+1}",
                    "timestamp": time.time()
                })
            }
            await asyncio.sleep(0.1)
        yield {
            "event": "done",
            "data": json.dumps({
                "type": "done",
                "timestamp": time.time(),
            })
        }
        
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
