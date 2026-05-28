"""
工具模块 - Tool System（Hermes 风格）

基于 registry 的自注册工具系统：
- 每个工具属于一个 toolset（file/terminal/browser/web/skill/mcp 等）
- 工具模块在模块级调用 registry.register() 自注册
- 线程安全：所有状态变更通过锁保护
- MCP/Plugin 工具可动态注册/注销
"""

from app.tools.registry import (
    ToolRegistry, ToolEntry, registry,
    discover_builtin_tools, discover_mcp_tools,
    tool_error, tool_result,
)

__all__ = [
    'ToolRegistry', 'ToolEntry', 'registry',
    'discover_builtin_tools', 'discover_mcp_tools',
    'tool_error', 'tool_result',
]
