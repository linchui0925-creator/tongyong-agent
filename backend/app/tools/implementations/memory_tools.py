"""
Memory tools — explicit, on-demand memory retrieval.

Do not auto-inject cross-session memories into prompts. Agents must call these
tools only when the user asks for remembered facts, prior decisions, preferences,
or history from another session.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.memory.storage import MemoryStorage
from app.memory.vector import VectorStore
from app.services.llm_manager import get_llm_manager
from app.tools.registry import registry

logger = logging.getLogger(__name__)


MEMORY_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "要检索的记忆问题或关键词。",
        },
        "session_id": {
            "type": "string",
            "description": "可选。只检索指定会话的记忆；不传则检索共享/跨会话记忆。",
        },
        "scope": {
            "type": "string",
            "enum": ["shared", "session", "all"],
            "description": "检索范围：shared=共享/跨会话记忆，session=指定会话记忆，all=全部记忆。",
            "default": "shared",
        },
        "k": {
            "type": "integer",
            "description": "最多返回条数。",
            "default": 5,
            "minimum": 1,
            "maximum": 20,
        },
    },
    "required": ["query"],
}


MEMORY_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "可选。指定会话 ID；不传则列出共享/跨会话记忆。",
        },
        "scope": {
            "type": "string",
            "enum": ["shared", "session", "all"],
            "description": "列表范围：shared=共享/跨会话记忆，session=指定会话记忆，all=全部记忆。",
            "default": "shared",
        },
        "limit": {
            "type": "integer",
            "description": "最多返回条数。",
            "default": 10,
            "minimum": 1,
            "maximum": 50,
        },
    },
    "required": [],
}


def _memory_to_dict(memory) -> dict:
    return {
        "id": getattr(memory, "id", ""),
        "type": getattr(memory, "type", ""),
        "content": getattr(memory, "content", ""),
        "importance": getattr(memory, "importance", 1),
        "session_id": getattr(memory, "session_id", None),
        "created_at": getattr(memory, "created_at", ""),
    }


async def memory_search_tool(
    query: str,
    session_id: Optional[str] = None,
    scope: str = "shared",
    k: int = 5,
) -> str:
    """Search memories explicitly instead of prompt auto-injection."""
    query = (query or "").strip()
    if not query:
        return "记忆检索失败: query 不能为空"

    k = max(1, min(int(k or 5), 20))
    scope = scope if scope in {"shared", "session", "all"} else "shared"

    llm = get_llm_manager().get_current_llm()
    vector_store = VectorStore()
    memories = []

    if llm and vector_store.collection:
        try:
            embedding = await llm.get_embedding(query)
            if scope == "session":
                if not session_id:
                    return "记忆检索失败: scope=session 时必须提供 session_id"
                memories = await vector_store.search(query, embedding, k=k, session_id=session_id)
            elif scope == "all":
                memories = await vector_store.search(query, embedding, k=k, session_id=None)
            else:
                memories = await vector_store.search(query, embedding, k=k, session_id=None, is_shared=True)
        except Exception as exc:
            logger.warning("向量记忆检索失败，降级 SQLite: %s", exc)

    if not memories:
        storage = MemoryStorage()
        if scope == "session":
            if not session_id:
                return "记忆检索失败: scope=session 时必须提供 session_id"
            candidates = await storage.get_memories(session_id)
        else:
            candidates = await storage.get_memories(None)
            if scope == "shared":
                candidates = [m for m in candidates if not getattr(m, "session_id", None)]
        q = query.casefold()
        memories = [
            m for m in candidates
            if q in (getattr(m, "content", "") or "").casefold()
            or q in (getattr(m, "type", "") or "").casefold()
        ][:k]

    payload = {
        "query": query,
        "scope": scope,
        "session_id": session_id,
        "count": len(memories),
        "memories": [_memory_to_dict(m) for m in memories[:k]],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def memory_list_tool(
    session_id: Optional[str] = None,
    scope: str = "shared",
    limit: int = 10,
) -> str:
    """List memories explicitly."""
    limit = max(1, min(int(limit or 10), 50))
    scope = scope if scope in {"shared", "session", "all"} else "shared"
    storage = MemoryStorage()

    if scope == "session":
        if not session_id:
            return "记忆列表失败: scope=session 时必须提供 session_id"
        memories = await storage.get_memories(session_id)
    else:
        memories = await storage.get_memories(None)
        if scope == "shared":
            memories = [m for m in memories if not getattr(m, "session_id", None)]

    payload = {
        "scope": scope,
        "session_id": session_id,
        "count": min(len(memories), limit),
        "memories": [_memory_to_dict(m) for m in memories[:limit]],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _check_env() -> bool:
    return True


def _register_tools():
    registry.register(
        name="memory_search",
        toolset="memory",
        description=(
            "按需检索记忆。只有当用户明确询问历史、偏好、长期记忆、之前结论、"
            "跨会话信息或需要回忆上下文时才调用。默认检索共享/跨会话记忆。"
        ),
        schema=MEMORY_SEARCH_SCHEMA,
        handler=memory_search_tool,
        check_fn=_check_env,
        emoji="🧠",
        parallel_mode="safe",
        max_result_size_chars=12000,
    )
    registry.register(
        name="memory_list",
        toolset="memory",
        description=(
            "按需列出记忆。只有用户要求查看记忆、列出偏好、查看历史记录时才调用。"
        ),
        schema=MEMORY_LIST_SCHEMA,
        handler=memory_list_tool,
        check_fn=_check_env,
        emoji="🧠",
        parallel_mode="safe",
        max_result_size_chars=12000,
    )


_register_tools()
