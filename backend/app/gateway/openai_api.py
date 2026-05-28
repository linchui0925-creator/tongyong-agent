"""
OpenAI-compatible API — v1/chat/completions

Any OpenAI-compatible frontend (Open WebUI, LobeChat, LibreChat,
Cursor, etc.) can connect to TongYong Agent through these endpoints.

遵循 Hermes Gateway 的 api_server.py 设计模式，集成 FastAPI 原生实现。
"""

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.gateway.auth import verify_api_key, init_auth
from app.gateway.config import GatewaySettings, Profile
from app.gateway.profile_manager import profile_manager
from app.core.agent import AgentEngine
from app.core.base import Message

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])

# ── 常量 ────────────────────────────────────────────────────

_MAX_CONTENT_PARTS = 1000
_MAX_TEXT_LENGTH = 65536

# ── 内部状态 ────────────────────────────────────────────────

_gateway_settings: GatewaySettings | None = None


def init_gateway(settings: GatewaySettings):
    global _gateway_settings
    _gateway_settings = settings
    init_auth(settings)


# ── 工具函数 ────────────────────────────────────────────────


def _normalize_content(content: Any) -> str:
    """归一化 OpenAI chat 消息内容为纯文本。

    Open WebUI / LobeChat 等前端可能将 content 发送为数组格式：
        [{"type": "text", "text": "hello"}, {"type": "input_text", "text": "..."}]
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:_MAX_TEXT_LENGTH]

    if isinstance(content, list):
        parts: List[str] = []
        for item in content[:_MAX_CONTENT_PARTS]:
            if isinstance(item, str):
                if item:
                    parts.append(item[:_MAX_TEXT_LENGTH])
            elif isinstance(item, dict):
                t = str(item.get("type", "")).strip().lower()
                if t in ("text", "input_text", "output_text"):
                    text = item.get("text", "")
                    if text:
                        parts.append(str(text)[:_MAX_TEXT_LENGTH])
        result = "\n".join(parts)
        return result[:_MAX_TEXT_LENGTH]

    try:
        return str(content)[:_MAX_TEXT_LENGTH]
    except Exception:
        return ""


def _derive_session_id(system_prompt: str, first_user_msg: str) -> str:
    """从对话内容推导稳定的会话 ID。

    OpenAI 前端每次请求都会发送完整历史。同一对话的首条用户消息
    和系统提示是恒定的，可以哈希出稳定的 session_id。
    """
    seed = f"{system_prompt or ''}\n{first_user_msg}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"api-{digest}"


def _build_chunk(
    response_id: str,
    model: str,
    content: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """构建 SSE chat completion chunk"""
    return {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content else {} if finish_reason else {"role": "assistant"},
                "finish_reason": finish_reason,
            }
        ],
    }


def _build_full_response(
    response_id: str,
    model: str,
    content: str,
) -> Dict[str, Any]:
    """构建非流式完整 response"""
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


# ── Profile Resolution ─────────────────────────────────────


async def _resolve_profile(request: Request) -> Optional[Profile]:
    """从请求中解析Profile：
    1. 路径 /v1/{profile_id}/chat/completions
    2. header X-Profile-Id
    3. query profile_id
    4. active profile
    """
    path_parts = request.url.path.strip("/").split("/")

    # 1. 路径解析: /v1/{profile_id}/chat/completions 或 /v1/{profile_id}/models
    if len(path_parts) >= 3 and path_parts[0] == "v1":
        profile_id_from_path = path_parts[1]
        # 排除chat/completions, models等标准端点
        if profile_id_from_path not in ("chat", "models", "health"):
            profile = profile_manager.get_profile(profile_id_from_path)
            if profile:
                return profile

    # 2. Header: X-Profile-Id
    profile_id = request.headers.get("X-Profile-Id")
    if profile_id:
        return profile_manager.get_profile(profile_id)

    # 3. Query: ?profile_id=
    profile_id = request.query_params.get("profile_id")
    if profile_id:
        return profile_manager.get_profile(profile_id)

    # 4. Fallback: active profile
    return profile_manager.get_active_profile()


# ── 获取 Agent Engine ─────────────────────────────────────


def _get_agent_engine() -> AgentEngine:
    """获取全局 AgentEngine 实例"""
    from app.main import agent_engine
    if agent_engine is None or agent_engine.llm is None:
        raise HTTPException(status_code=503, detail="Agent engine not initialized")
    return agent_engine


# ═══════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════


@router.get("/health")
async def health():
    """健康检查"""
    from app.main import agent_engine
    return {
        "status": "ok",
        "engine": agent_engine is not None and agent_engine.llm is not None,
    }


@router.get("/models")
async def list_models(request: Request):
    """列出可用模型（OpenAI 兼容）- 返回profile名称作为模型名"""
    profile = await _resolve_profile(request)

    if profile:
        model_name = profile.id  # profile ID作为模型名
        provider = profile.provider
    else:
        model_name = _gateway_settings.model_name if _gateway_settings else "tongyong-agent"
        provider = "tongyi"

    return {
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "tongyong",
                "profile_id": profile.id if profile else "default",
                "provider": provider,
            }
        ],
    }


@router.post("/chat/completions")
async def chat_completions(request: Request):
    """
    OpenAI Chat Completions API

    支持流式 (stream=true) 和非流式模式。
    会话连续性: 通过 X-Session-Id 请求头或内容哈希绑定。
    支持 X-Profile-Id header 或 profile_id query 参数切换Profile。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="Missing or invalid 'messages' field")

    stream = body.get("stream", False)
    model = body.get("model", _gateway_settings.model_name if _gateway_settings else "tongyong-agent")

    # ── Profile解析 ───────────────────────────────────────
    profile = await _resolve_profile(request)

    # ── 解析消息 ──────────────────────────────────────────
    system_prompt = None
    conversation: List[Dict[str, str]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = _normalize_content(msg.get("content", ""))
        if role == "system":
            system_prompt = (system_prompt + "\n" + content) if system_prompt else content
        elif role in ("user", "assistant"):
            conversation.append({"role": role, "content": content})

    if not conversation:
        raise HTTPException(status_code=400, detail="No user/assistant messages")

    # ── 会话 ID ───────────────────────────────────────────
    session_id = request.headers.get("X-Session-Id") or request.headers.get("X-Hermes-Session-Id")
    if not session_id:
        first_user = next((m["content"] for m in conversation if m["role"] == "user"), "")
        session_id = _derive_session_id(system_prompt or "", first_user)

    # ── Profile切换 ───────────────────────────────────────
    max_rounds = _gateway_settings.max_tool_rounds if _gateway_settings else 10
    profile_id = "default"
    if profile:
        profile_id = profile.id
        from app.services.llm_manager import get_llm_manager
        llm_mgr = get_llm_manager(profile_id)
        llm_mgr.switch_to_profile(profile)
        if profile.max_tool_rounds:
            max_rounds = profile.max_tool_rounds

    # ── 执行 ──────────────────────────────────────────────
    if stream:
        return EventSourceResponse(
            _stream_chat(session_id, system_prompt, conversation, model, max_rounds, profile_id)
        )

    content = await _run_chat(session_id, system_prompt, conversation, max_rounds, profile_id)
    response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    return _build_full_response(response_id, model, content)


# ═══════════════════════════════════════════════════════════
# 内部执行逻辑
# ═══════════════════════════════════════════════════════════


async def _prepare_context(system_prompt: Optional[str], profile_id: str = "default") -> List[Message]:
    """准备上下文消息列表：系统提示 + 领域认知 + Hermes记忆"""
    context_messages: List[Message] = []

    prompt_parts = []
    if system_prompt:
        prompt_parts.append(system_prompt)

    from app.core.domain_prompts import get_all_domain_prompts
    domain = get_all_domain_prompts()
    if domain:
        prompt_parts.append(domain)

    # 添加Hermes profile记忆
    from app.hermes.memory_file import MemoryFileManager
    memory_mgr = MemoryFileManager(profile_id=profile_id)
    memory_content = memory_mgr.load_memory()
    if memory_content:
        prompt_parts.append(f"[长期记忆]\n{memory_content}")

    if prompt_parts:
        context_messages.append(Message(
            role="system", content="\n\n".join(prompt_parts),
        ))

    return context_messages


async def _run_chat(
    session_id: str,
    system_prompt: Optional[str],
    conversation: List[Dict[str, str]],
    max_rounds: int = 10,
    profile_id: str = "default",
) -> str:
    """执行一轮对话（非流式）"""
    from app.tools.manager import get_tool_manager

    engine = _get_agent_engine()
    tool_mgr = get_tool_manager()
    tool_schemas = tool_mgr.get_schemas()

    # 构建消息列表
    context_messages = await _prepare_context(system_prompt, profile_id)
    for msg in conversation:
        context_messages.append(Message(role=msg["role"], content=msg["content"]))

    try:
        for round_num in range(max_rounds):
            llm_response = await engine.llm.chat(messages=context_messages, tools=tool_schemas)

            if not llm_response.has_tool_calls:
                return llm_response.content or ""

            # 处理工具调用
            for tc in llm_response.tool_calls:
                logger.info(f"工具调用 [{round_num}]: {tc.tool_name}({tc.arguments})")
                tool_result = await tool_mgr.execute(tc.tool_name, tc.arguments)

                context_messages.append(Message(
                    role="assistant",
                    content=json.dumps({
                        "tool_calls": [{
                            "id": tc.tool_call_id,
                            "type": "function",
                            "function": {"name": tc.tool_name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                        }],
                    }, ensure_ascii=False),
                ))
                context_messages.append(Message(
                    role="tool",
                    content=tool_result,
                ))

        return "工具调用轮次已达上限"
    except Exception as e:
        logger.error(f"Chat 执行失败: {e}", exc_info=True)
        return f"执行出错: {e}"


async def _stream_chat(
    session_id: str,
    system_prompt: Optional[str],
    conversation: List[Dict[str, str]],
    model: str,
    max_rounds: int = 10,
    profile_id: str = "default",
) -> AsyncGenerator[Dict[str, Any], None]:
    """SSE 流式对话"""
    from app.tools.manager import get_tool_manager

    response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    engine = _get_agent_engine()
    tool_mgr = get_tool_manager()
    tool_schemas = tool_mgr.get_schemas()

    context_messages = await _prepare_context(system_prompt, profile_id)
    for msg in conversation:
        context_messages.append(Message(role=msg["role"], content=msg["content"]))

    try:
        for round_num in range(max_rounds):
            llm_response = await engine.llm.chat(messages=context_messages, tools=tool_schemas)

            if not llm_response.has_tool_calls:
                content = llm_response.content or ""
                if content:
                    yield {
                        "event": "data",
                        "data": json.dumps(
                            _build_chunk(response_id, model, content=content),
                            ensure_ascii=False,
                        ),
                    }
                yield {
                    "event": "data",
                    "data": json.dumps(
                        _build_chunk(response_id, model, finish_reason="stop"),
                        ensure_ascii=False,
                    ),
                }
                yield {"event": "data", "data": "[DONE]"}
                return

            # 处理工具调用
            for tc in llm_response.tool_calls:
                logger.info(f"工具调用 [{round_num}]: {tc.tool_name}({tc.arguments})")

                yield {
                    "event": "data",
                    "data": json.dumps(
                        _build_chunk(response_id, model, content=f"\n⚙️ [{tc.tool_name}]...\n"),
                        ensure_ascii=False,
                    ),
                }

                tool_result = await tool_mgr.execute(tc.tool_name, tc.arguments)

                context_messages.append(Message(
                    role="assistant",
                    content=json.dumps({
                        "tool_calls": [{
                            "id": tc.tool_call_id,
                            "type": "function",
                            "function": {"name": tc.tool_name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                        }],
                    }, ensure_ascii=False),
                ))
                context_messages.append(Message(
                    role="tool",
                    content=tool_result,
                ))

    except Exception as e:
        logger.error(f"流式执行失败: {e}", exc_info=True)
        yield {
            "event": "data",
            "data": json.dumps(
                _build_chunk(response_id, model, finish_reason="error"),
                ensure_ascii=False,
            ),
        }
        yield {"event": "data", "data": "[DONE]"}

    # 兜底
    yield {
        "event": "data",
        "data": json.dumps(
            _build_chunk(response_id, model, finish_reason="stop"),
            ensure_ascii=False,
        ),
    }
    yield {"event": "data", "data": "[DONE]"}
