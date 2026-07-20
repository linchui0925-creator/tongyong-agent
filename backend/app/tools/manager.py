"""
ToolManager - 工具管理器（向后兼容层）

保持与 agent.py 中 get_tool_manager() / get_schemas() / execute(name, args) 的接口一致。
底层实现委托给 registry 单例。
"""

import logging
from typing import Dict, Any, List

from app.tools.registry import registry, discover_builtin_tools

logger = logging.getLogger(__name__)


# W5-8: 高风险工具 — 走 runtime AsyncCallGuard (超时 + 熔断 + trace span)。
# 这些工具会起子进程 / 跑命令 / 访问外部, 卡死或反复失败风险最高。
_HIGH_RISK_TOOLS = frozenset({
    "terminal", "workspace_terminal", "browser", "cdp", "desktop", "adb",
})
# 每个高风险工具的单次超时 (秒); 未列出的用 guard.default_timeout。
_TOOL_TIMEOUTS = {
    "terminal": 120.0,
    "workspace_terminal": 180.0,
    "browser": 90.0,
    "cdp": 90.0,
    "desktop": 60.0,
    "adb": 60.0,
}


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
        # W5-8: 高风险工具经 AsyncCallGuard 治理 (超时 + 熔断); 其他直通。
        if tool_name in _HIGH_RISK_TOOLS and _guard_enabled():
            try:
                from app.core.runtime.ipc import get_guard
                from app.core.delivery_gate import _is_error_result
                guard = get_guard()
                return await guard.run(
                    tool_name,
                    lambda: registry.execute(tool_name, arguments),
                    timeout=_TOOL_TIMEOUTS.get(tool_name),
                    is_error=_is_error_result,
                )
            except Exception as e:  # guard 自身异常绝不能挡住工具执行
                logger.debug(f"AsyncCallGuard 跳过 ({tool_name}): {e}")
        return await registry.execute(tool_name, arguments)


def _guard_enabled() -> bool:
    try:
        from app.config import settings
        return bool(getattr(settings, "runtime_tool_guard_enabled", True))
    except Exception:
        return True


# 全局单例
_manager: ToolManager | None = None


def get_tool_manager() -> ToolManager:
    global _manager
    if _manager is None:
        _manager = ToolManager()
    return _manager
