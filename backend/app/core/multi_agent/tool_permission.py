"""
ToolPermission - Agent 工具权限模型
白名单优先 + 黑名单兜底 + 默认全开
"""

from pydantic import BaseModel, Field
from typing import List, Optional

class ToolPermission(BaseModel):
    """Agent 的工具权限配置"""
    allowed_tools: List[str] = Field(default_factory=list)   # 允许的工具列表（空=全部）
    denied_tools: List[str] = Field(default_factory=list)   # 拒绝的工具列表
    max_tool_turns: int = 20                                # 最大工具调用轮次
    
    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否允许使用"""
        if self.allowed_tools:
            return tool_name in self.allowed_tools
        return tool_name not in self.denied_tools
    
    def filter_schemas(self, schemas: List[dict]) -> List[dict]:
        """根据权限过滤 LLM schema"""
        result = []
        for s in schemas:
            name = s.get("function", {}).get("name") or s.get("name", "")
            if self.is_tool_allowed(name):
                result.append(s)
        return result
    
    def summary(self) -> str:
        if not self.allowed_tools and not self.denied_tools:
            return "全部工具可用"
        if self.allowed_tools:
            return f"可用工具: {', '.join(self.allowed_tools)}"
        return f"禁止工具: {', '.join(self.denied_tools)}"