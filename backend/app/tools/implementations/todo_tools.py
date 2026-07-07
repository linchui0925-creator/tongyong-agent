"""
todo_tools - Lightweight task checklist tools for long agent runs.

The checklist is intentionally session-scoped and in-memory. It gives the model
a structured way to expose progress during one long task without polluting
cross-session memory.
"""

import json
import threading
from typing import Any, Dict, List, Optional

from app.tools.registry import registry


_LOCK = threading.RLock()
_TODOS: Dict[str, List[Dict[str, Any]]] = {}
_ALLOWED_STATUSES = {"pending", "in_progress", "completed", "blocked"}


TODO_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": "任务项内容，必须是可验证的具体动作",
        },
        "status": {
            "type": "string",
            "enum": sorted(_ALLOWED_STATUSES),
            "description": "任务状态",
        },
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "可选优先级",
        },
    },
    "required": ["content", "status"],
}


TODO_WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "items": TODO_ITEM_SCHEMA,
            "minItems": 1,
            "maxItems": 20,
            "description": "完整 checklist。每次调用都会替换当前会话的列表。",
        },
        "session_id": {
            "type": "string",
            "description": "会话 ID。缺省时写入 default 临时列表。",
        },
    },
    "required": ["todos"],
}


TODO_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "会话 ID。缺省时读取 default 临时列表。",
        },
    },
}


def _normalize_session_id(session_id: Optional[str]) -> str:
    return str(session_id or "default")


def _normalize_todos(todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(todos, list) or not todos:
        raise ValueError("todos 必须是非空数组")
    if len(todos) > 20:
        raise ValueError("todos 最多 20 项")

    normalized = []
    active_count = 0
    for index, item in enumerate(todos, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 项必须是对象")
        content = str(item.get("content", "")).strip()
        status = str(item.get("status", "")).strip()
        priority = str(item.get("priority", "medium")).strip() or "medium"

        if not content:
            raise ValueError(f"第 {index} 项 content 不能为空")
        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"第 {index} 项 status 无效: {status}")
        if priority not in {"low", "medium", "high"}:
            priority = "medium"
        if status == "in_progress":
            active_count += 1

        normalized.append({
            "id": index,
            "content": content,
            "status": status,
            "priority": priority,
        })

    if active_count > 1:
        raise ValueError("同一时间最多只能有一个 in_progress 任务")
    return normalized


async def todo_write_tool(
    todos: List[Dict[str, Any]],
    session_id: Optional[str] = None,
) -> str:
    sid = _normalize_session_id(session_id)
    normalized = _normalize_todos(todos)
    with _LOCK:
        _TODOS[sid] = normalized
    return json.dumps({
        "session_id": sid,
        "total": len(normalized),
        "todos": normalized,
    }, ensure_ascii=False)


async def todo_read_tool(session_id: Optional[str] = None) -> str:
    sid = _normalize_session_id(session_id)
    with _LOCK:
        todos = list(_TODOS.get(sid, []))
    return json.dumps({
        "session_id": sid,
        "total": len(todos),
        "todos": todos,
    }, ensure_ascii=False)


def _register_tools():
    registry.register(
        name="todo_write",
        toolset="planning",
        description=(
            "创建或更新当前长任务 checklist。适用于多步骤前端/后端/测试任务，"
            "开始时写计划，执行过程中逐项更新状态；每次传完整列表。"
        ),
        schema=TODO_WRITE_SCHEMA,
        handler=todo_write_tool,
        is_async=True,
        emoji="✓",
        parallel_mode="never",
    )
    registry.register(
        name="todo_read",
        toolset="planning",
        description="读取当前会话 checklist，用于恢复长任务进度。",
        schema=TODO_READ_SCHEMA,
        handler=todo_read_tool,
        is_async=True,
        emoji="✓",
        parallel_mode="safe",
    )


_register_tools()
