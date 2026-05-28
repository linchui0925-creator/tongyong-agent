"""
BaseTool - 工具抽象基类

所有内置工具继承此类，统一接口规范。
工具定义采用 OpenAI function calling 格式。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseTool(ABC):
    """工具抽象基类"""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    def to_schema(self) -> Dict[str, Any]:
        """转为 OpenAI function calling schema 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具，返回结果文本"""
        ...
