"""
BaseDomainExecutor - 领域执行器抽象基类

所有领域执行器统一接口，确保 AgentEngine 可以用一致的方式调用各领域能力。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List


class BaseDomainExecutor(ABC):
    """领域执行器基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """领域名称"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """领域描述"""
        ...

    @abstractmethod
    async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行领域动作

        Args:
            action: 动作名称 (如 "run", "list", "create")
            params: 动作参数

        Returns:
            Dict: 执行结果，包含 success, result/error 字段
        """
        ...

    def get_capabilities(self) -> List[Dict[str, Any]]:
        """
        返回该领域支持的能力列表

        返回格式: [{"action": "run", "description": "运行命令", "params": {...}}, ...]
        """
        return []

    def get_info(self) -> Dict[str, Any]:
        """获取领域信息"""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": self.get_capabilities(),
        }
