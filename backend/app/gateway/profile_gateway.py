"""
ProfileGateway - Profile独立网关进程

每个Profile有独立的FastAPI应用，监听独立端口。
通过环境变量 PROFILE_ID 确定使用哪个Profile配置。
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# 设置后端路径
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

# 读取Profile ID
PROFILE_ID = os.environ.get("PROFILE_ID", "default")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s - [Profile:{PROFILE_ID}] - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

logger.info(f"ProfileGateway 启动中, Profile ID: {PROFILE_ID}")

# ── Profile专属资源初始化 ─────────────────────────────────

# 初始化Profile专属的MemoryStorage和VectorStore
from app.memory.storage import MemoryStorage
from app.memory.vector import VectorStore
from app.hermes.memory_file import MemoryFileManager
from app.services.llm_manager import get_llm_manager
from app.gateway.profile_manager import profile_manager

# 创建Profile专属资源实例
_storage: Optional[MemoryStorage] = None
_vector_store: Optional[VectorStore] = None
_memory_file: Optional[MemoryFileManager] = None
_llm_manager = None


def get_storage() -> MemoryStorage:
    """获取当前Profile的MemoryStorage"""
    global _storage
    if _storage is None:
        _storage = MemoryStorage(profile_id=PROFILE_ID)
    return _storage


def get_vector_store() -> VectorStore:
    """获取当前Profile的VectorStore"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(profile_id=PROFILE_ID)
    return _vector_store


def get_memory_file() -> MemoryFileManager:
    """获取当前Profile的MemoryFileManager"""
    global _memory_file
    if _memory_file is None:
        _memory_file = MemoryFileManager(profile_id=PROFILE_ID)
    return _memory_file


def get_llm_mgr():
    """获取当前Profile的LLMManager"""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = get_llm_manager(PROFILE_ID)
    return _llm_manager


# ── FastAPI 应用 ──────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.core.agent import AgentEngine
from app.core.base import Message

import json
import time
import uuid
from typing import Any, Dict, List, AsyncGenerator

app = FastAPI(
    title=f"TongYong Agent - Profile Gateway ({PROFILE_ID})",
    version="1.0.0",
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 工具函数 ───────────────────────────────────────────────


def _normalize_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:65536]
    if isinstance(content, list):
        parts = []
        for item in content[:1000]:
            if isinstance(item, str) and item:
                parts.append(item[:65536])
            elif isinstance(item, dict):
                t = str(item.get("type", "")).strip().lower()
                if t in ("text", "input_text", "output_text"):
                    text = item.get("text", "")
                    if text:
                        parts.append(str(text)[:65536])
        return "\n".join(parts)[:65536]
    try:
        return str(content)[:65536]
    except Exception:
        return ""


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


# ── 路由 ──────────────────────────────────────────────────


@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "profile_id": PROFILE_ID,
        "provider": profile_manager.get_profile(PROFILE_ID).provider if profile_manager.get_profile(PROFILE_ID) else None,
    }


@app.get("/v1/models")
async def list_models():
    """列出可用模型"""
    profile = profile_manager.get_profile(PROFILE_ID)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {PROFILE_ID} not found")

    from app.llm.model_metadata import get_provider_models
    models = get_provider_models(profile.provider)

    return {
        "object": "list",
        "data": [{
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": profile.provider,
            "provider": profile.provider,
        } for model_id in models]
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Chat Completions API"""
    profile = profile_manager.get_profile(PROFILE_ID)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {PROFILE_ID} not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="Missing or invalid 'messages' field")

    stream = body.get("stream", False)
    model = body.get("model", profile.model or "default")

    # 解析消息
    system_prompt = None
    conversation = []
    for msg in messages:
        role = msg.get("role", "")
        content = _normalize_content(msg.get("content", ""))
        if role == "system":
            system_prompt = (system_prompt + "\n" + content) if system_prompt else content
        elif role in ("user", "assistant"):
            conversation.append({"role": role, "content": content})

    if not conversation:
        raise HTTPException(status_code=400, detail="No user/assistant messages")

    # Profile切换
    max_rounds = profile.max_tool_rounds if profile.max_tool_rounds else 10

    llm_mgr = get_llm_mgr()
    llm_mgr.switch_to_profile(profile)

    if stream:
        return EventSourceResponse(
            _stream_chat(PROFILE_ID, system_prompt, conversation, model, max_rounds)
        )

    content = await _run_chat(PROFILE_ID, system_prompt, conversation, max_rounds)
    response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    return _build_full_response(response_id, model, content)


# ── 内部执行逻辑 ───────────────────────────────────────────


async def _prepare_context(system_prompt: Optional[str]) -> List[Message]:
    """准备上下文消息"""
    context_messages = []
    prompt_parts = []

    if system_prompt:
        prompt_parts.append(system_prompt)

    # 添加领域认知
    from app.core.domain_prompts import get_all_domain_prompts
    domain = get_all_domain_prompts()
    if domain:
        prompt_parts.append(domain)

    # 添加Hermes记忆
    memory_mgr = get_memory_file()
    memory_content = memory_mgr.load_memory()
    if memory_content:
        prompt_parts.append(f"[长期记忆]\n{memory_content}")

    if prompt_parts:
        context_messages.append(Message(role="system", content="\n\n".join(prompt_parts)))

    return context_messages


async def _run_chat(profile_id: str, system_prompt: Optional[str], conversation: List[Dict[str, str]], max_rounds: int) -> str:
    """执行非流式对话"""
    from app.tools.manager import get_tool_manager

    engine = AgentEngine(llm=None)
    tool_mgr = get_tool_manager()
    tool_schemas = tool_mgr.get_schemas()

    # 获取当前Profile的LLM
    llm_mgr = get_llm_mgr()
    llm = llm_mgr.get_current_llm()
    if llm is None:
        return "LLM未初始化"

    engine.llm = llm

    context_messages = await _prepare_context(system_prompt)
    for msg in conversation:
        context_messages.append(Message(role=msg["role"], content=msg["content"]))

    try:
        for round_num in range(max_rounds):
            llm_response = await engine.llm.chat(messages=context_messages, tools=tool_schemas)

            if not llm_response.has_tool_calls:
                return llm_response.content or ""

            for tc in llm_response.tool_calls:
                logger.info(f"[{profile_id}] 工具调用: {tc.tool_name}({tc.arguments})")
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


async def _stream_chat(profile_id: str, system_prompt: Optional[str], conversation: List[Dict[str, str]], model: str, max_rounds: int) -> AsyncGenerator[Dict[str, Any], None]:
    """SSE流式对话"""
    from app.tools.manager import get_tool_manager

    response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    engine = AgentEngine(llm=None)
    tool_mgr = get_tool_manager()
    tool_schemas = tool_mgr.get_schemas()

    llm_mgr = get_llm_mgr()
    llm = llm_mgr.get_current_llm()
    if llm is None:
        yield {"event": "data", "data": json.dumps({"error": "LLM未初始化"}, ensure_ascii=False)}
        return

    engine.llm = llm

    context_messages = await _prepare_context(system_prompt)
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
                logger.info(f"[{profile_id}] 工具调用: {tc.tool_name}({tc.arguments})")
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


# ── 启动信息 ───────────────────────────────────────────────

logger.info(f"ProfileGateway [{PROFILE_ID}] 初始化完成")
