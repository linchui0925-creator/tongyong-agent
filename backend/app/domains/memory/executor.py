"""
MemoryExecutor - 记忆操作执行器

提供记忆 CRUD 和梦境操作能力，包装 MemoryStorage 和 DreamingEngine。
"""

from typing import Dict, Any, List, Optional
import logging

from app.domains.base import BaseDomainExecutor

logger = logging.getLogger(__name__)


class MemoryExecutor(BaseDomainExecutor):
    """记忆执行器"""

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return "记忆与梦境系统：查看、添加、搜索记忆，触发梦境反思"

    def __init__(self, memory_storage=None, vector_store=None, dreaming_engine=None):
        self.memory_storage = memory_storage
        self.vector_store = vector_store
        self.dreaming_engine = dreaming_engine

    async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action == "trigger_dream":
            if self.dreaming_engine:
                try:
                    result = await self.dreaming_engine.run_full_sweep()
                    return {"success": True, "result": result}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": "梦境引擎未初始化"}

        elif action == "search":
            query = params.get("query", "")
            k = params.get("k", 5)
            session_id = params.get("session_id")
            if self.vector_store and self.memory_storage:
                try:
                    memories = await self.memory_storage.get_memories(session_id)
                    return {"success": True, "memories": [m.content for m in memories[:k]]}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": "记忆存储未初始化"}

        elif action == "status":
            if self.dreaming_engine:
                try:
                    status = await self.dreaming_engine.get_status()
                    return {"success": True, "status": status}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": "梦境引擎未初始化"}

        return {"success": False, "error": f"不支持的动作: {action}"}

    def get_capabilities(self) -> List[Dict[str, Any]]:
        return [
            {"action": "trigger_dream", "description": "触发梦境扫描，分析对话并提炼长期记忆"},
            {"action": "search", "description": "搜索记忆", "params": {"query": "搜索关键词", "k": "返回条数"}},
            {"action": "status", "description": "查看梦境系统状态"},
        ]
