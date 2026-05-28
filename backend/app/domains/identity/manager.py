"""
IdentityManager - 身份管理

管理 Agent 的身份设定和人格配置。
"""

from typing import Dict, Any, List, Optional
import logging

from app.domains.base import BaseDomainExecutor

logger = logging.getLogger(__name__)


class IdentityManager(BaseDomainExecutor):
    """身份管理器"""

    @property
    def name(self) -> str:
        return "identity"

    @property
    def description(self) -> str:
        return "身份与人格管理：查看和管理 Agent 身份设定和用户画像"

    def __init__(self, memory_file_manager=None):
        self.memory_file_manager = memory_file_manager

    async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action == "whoami":
            return {
                "success": True,
                "identity": "TongYong Agent（同通用智能体）",
                "description": "一个具备多种能力的 AI 编程助手",
            }

        elif action == "read_memory":
            if self.memory_file_manager:
                content = self.memory_file_manager.read_memory()
                return {"success": True, "content": content}
            return {"success": False, "error": "记忆管理器未初始化"}

        elif action == "read_user":
            if self.memory_file_manager:
                content = self.memory_file_manager.read_user()
                return {"success": True, "content": content}
            return {"success": False, "error": "用户画像管理器未初始化"}

        return {"success": False, "error": f"不支持的动作: {action}"}

    def get_capabilities(self) -> List[Dict[str, Any]]:
        return [
            {"action": "whoami", "description": "查看当前 Agent 身份"},
            {"action": "read_memory", "description": "读取 MEMORY.md 人格设定"},
            {"action": "read_user", "description": "读取 USER.md 用户画像"},
        ]
