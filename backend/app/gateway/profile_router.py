"""
ProfileRouter - Profile独立的网关路由

支持 /v1/{profile}/chat/completions 和 /v1/{profile}/models 路径
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.gateway.auth import verify_api_key
from app.gateway.profile_manager import profile_manager
from app.core.agent import AgentEngine
from app.core.base import Message

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_api_key)])

_MAX_CONTENT_PARTS = 1000
_MAX_TEXT_LENGTH = 65536


# ── 工具函数 ────────────────────────────────────────────────


def _normalize_content(content: Any) -> str:
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
    seed = f"{system_prompt or ''}\n{first_user_msg}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"api-{digest}"


def _build_chunk(response_id: str, model: str, content: Optional[str] = None, finish_reason: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": content} if content else {} if finish_reason else {"role": "assistant"}, "finish_reason": finish_reason}],
    }


def _build_full_response(response_id: str, model: str, content: str) -> Dict[str, Any]:
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }


# ── 获取AgentEngine ─────────────────────────────────────


def _get_agent_engine() -> AgentEngine:
    from app.main import agent_engine
    if agent_engine is None or agent_engine.llm is None:
        raise HTTPException(status_code=503, detail="Agent engine not initialized")
    return agent_engine


# ═══════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════


@router.get("/{profile_id}/models")
async def list_models(profile_id: str):
    """列出指定Profile的可用模型"""
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")

    return {
        "object": "list",
        "data": [{
            "id": profile_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "tongyong",
            "profile_id": profile_id,
            "provider": profile.provider,
        }],
    }


@router.post("/{profile_id}/chat/completions")
async def chat_completions(profile_id: str, request: Request):
    """Profile独立的Chat Completions API"""
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="Missing or invalid 'messages' field")

    stream = body.get("stream", False)
    model = body.get("model", profile_id)

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
    max_rounds = profile.max_tool_rounds if profile.max_tool_rounds else 10

    from app.services.llm_manager import get_llm_manager
    llm_mgr = get_llm_manager(profile_id)
    llm_mgr.switch_to_profile(profile)

    # ── 执行 ──────────────────────────────────────────────
    if stream:
        return EventSourceResponse(
            _stream_chat(profile_id, session_id, system_prompt, conversation, model, max_rounds)
        )

    content = await _run_chat(profile_id, session_id, system_prompt, conversation, max_rounds)
    response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    return _build_full_response(response_id, model, content)


# ═══════════════════════════════════════════════════════════
# 内部执行逻辑
# ═══════════════════════════════════════════════════════════


async def _prepare_context(profile_id: str, system_prompt: Optional[str]) -> List[Message]:
    """准备上下文消息列表"""
    context_messages: List[Message] = []

    prompt_parts = []
    if system_prompt:
        prompt_parts.append(system_prompt)

    from app.core.domain_prompts import get_all_domain_prompts
    domain = get_all_domain_prompts()
    if domain:
        prompt_parts.append(domain)

    from app.hermes.memory_file import MemoryFileManager
    memory_mgr = MemoryFileManager(profile_id=profile_id)
    memory_content = memory_mgr.load_memory()
    if memory_content:
        prompt_parts.append(f"[长期记忆]\n{memory_content}")

    if prompt_parts:
        context_messages.append(Message(role="system", content="\n\n".join(prompt_parts)))

    return context_messages


async def _run_chat(profile_id: str, session_id: str, system_prompt: Optional[str], conversation: List[Dict[str, str]], max_rounds: int) -> str:
    """执行非流式对话"""
    from app.tools.manager import get_tool_manager

    engine = _get_agent_engine()
    tool_mgr = get_tool_manager()
    tool_schemas = tool_mgr.get_schemas()

    context_messages = await _prepare_context(profile_id, system_prompt)
    for msg in conversation:
        context_messages.append(Message(role=msg["role"], content=msg["content"]))

    try:
        for round_num in range(max_rounds):
            llm_response = await engine.llm.chat(messages=context_messages, tools=tool_schemas)

            if not llm_response.has_tool_calls:
                return llm_response.content or ""

            for tc in llm_response.tool_calls:
                logger.info(f"[{profile_id}] 工具调用 [{round_num}]: {tc.tool_name}({tc.arguments})")
                tool_result = await tool_mgr.execute(tc.tool_name, tc.arguments)

                context_messages.append(Message(
                    role="assistant",
                    content=json.dumps({"tool_calls": [{"id": tc.tool_call_id, "type": "function", "function": {"name": tc.tool_name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}]}, ensure_ascii=False),
                ))
                context_messages.append(Message(role="tool", content=tool_result))

        return "工具调用轮次已达上限"
    except Exception as e:
        logger.error(f"[{profile_id}] Chat执行失败: {e}", exc_info=True)
        return f"执行出错: {e}"


async def _stream_chat(profile_id: str, session_id: str, system_prompt: Optional[str], conversation: List[Dict[str, str]], model: str, max_rounds: int) -> AsyncGenerator[Dict[str, Any], None]:
    """SSE流式对话"""
    from app.tools.manager import get_tool_manager

    response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    engine = _get_agent_engine()
    tool_mgr = get_tool_manager()
    tool_schemas = tool_mgr.get_schemas()

    context_messages = await _prepare_context(profile_id, system_prompt)
    for msg in conversation:
        context_messages.append(Message(role=msg["role"], content=msg["content"]))

    try:
        for round_num in range(max_rounds):
            llm_response = await engine.llm.chat(messages=context_messages, tools=tool_schemas)

            if not llm_response.has_tool_calls:
                content = llm_response.content or ""
                if content:
                    yield {"event": "data", "data": json.dumps(_build_chunk(response_id, model, content=content), ensure_ascii=False)}
                yield {"event": "data", "data": json.dumps(_build_chunk(response_id, model, finish_reason="stop"), ensure_ascii=False)}
                yield {"event": "data", "data": "[DONE]"}
                return

            for tc in llm_response.tool_calls:
                logger.info(f"[{profile_id}] 工具调用 [{round_num}]: {tc.tool_name}({tc.arguments})")
                yield {"event": "data", "data": json.dumps(_build_chunk(response_id, model, content=f"\n⚙️ [{tc.tool_name}]...\n"), ensure_ascii=False)}
                tool_result = await tool_mgr.execute(tc.tool_name, tc.arguments)
                context_messages.append(Message(role="assistant", content=json.dumps({"tool_calls": [{"id": tc.tool_call_id, "type": "function", "function": {"name": tc.tool_name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}]}, ensure_ascii=False)))
                context_messages.append(Message(role="tool", content=tool_result))

    except Exception as e:
        logger.error(f"[{profile_id}] 流式执行失败: {e}", exc_info=True)
        yield {"event": "data", "data": json.dumps(_build_chunk(response_id, model, finish_reason="error"), ensure_ascii=False)}
        yield {"event": "data", "data": "[DONE]"}

    yield {"event": "data", "data": json.dumps(_build_chunk(response_id, model, finish_reason="stop"), ensure_ascii=False)}
    yield {"event": "data", "data": "[DONE]"}