"""
ToolManager - 工具管理器（向后兼容层）

保持与 agent.py 中 get_tool_manager() / get_schemas() / execute(name, args) 的接口一致。
底层实现委托给 registry 单例。
"""

import logging
from typing import Dict, Any, List

from app.tools.registry import registry, discover_builtin_tools

logger = logging.getLogger(__name__)


class ToolManager:
    """工具管理器 - 委托给 registry"""

    def __init__(self):
        # 始终执行发现 — importlib.import_module 对已导入模块是幂等的
        discover_builtin_tools()
        logger.info(f"ToolManager 初始化，可用工具: {registry.get_all_tool_names()}")

    def get_schemas(self) -> List[Dict[str, Any]]:
        return registry.get_schemas()

    def get_tool(self, name: str):
        return registry.get_entry(name)

    def list_tools(self) -> List[str]:
        return registry.get_all_tool_names()

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        return await registry.execute(tool_name, arguments)


# 全局单例
_manager: ToolManager | None = None


def get_tool_manager() -> ToolManager:
    global _manager
    if _manager is None:
        _manager = ToolManager()
    return _manager
