"""
ToolsExecutor - 工具执行框架

提供安全的工具执行能力，包装 ToolRegistry 和权限管理。
"""

from typing import Dict, Any, List, Optional
import logging

from app.domains.base import BaseDomainExecutor

logger = logging.getLogger(__name__)


class ToolsExecutor(BaseDomainExecutor):
    """工具执行器"""

    @property
    def name(self) -> str:
        return "tools"

    @property
    def description(self) -> str:
        return "工具执行框架：安全执行文件操作、项目分析等工具"

    def __init__(self):
        self._tools = {}

    def register_tool(self, name: str, description: str, func):
        """注册一个工具"""
        self._tools[name] = {"description": description, "func": func}
        logger.info(f"工具已注册: {name}")

    async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action == "list":
            return {"success": True, "tools": list(self._tools.keys())}

        elif action == "run":
            tool_name = params.get("tool", "")
            if tool_name not in self._tools:
                return {"success": False, "error": f"工具不存在: {tool_name}"}
            try:
                tool_func = self._tools[tool_name]["func"]
                result = await tool_func(**params.get("args", {}))
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": f"不支持的动作: {action}"}

    def get_capabilities(self) -> List[Dict[str, Any]]:
        tools = [
            {"action": "list", "description": "列出所有可用工具"},
            {"action": "run", "description": "执行指定工具", "params": {"tool": "工具名称", "args": "工具参数"}},
        ]
        for name, info in self._tools.items():
            tools.append({"action": name, "description": info["description"]})
        return tools
