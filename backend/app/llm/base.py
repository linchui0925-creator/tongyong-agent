"""
LLM基类 - 定义LLM接口规范
提供统一的chat和embedding方法，支持多种LLM提供商
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncIterator, Union
from app.core.base import Message
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolCallResult:
    """工具调用结果"""
    tool_name: str
    arguments: Dict[str, Any]
    tool_call_id: str = ""


class LLMResponse:
    """LLM响应，支持纯文本和工具调用"""

    def __init__(self, content: str = "", tool_calls: Optional[List[ToolCallResult]] = None, thinking: Optional[List[str]] = None, usage: Optional[Dict[str, int]] = None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.thinking = thinking or []
        self.usage = usage or {}  # {"input_tokens": int, "output_tokens": int, "total_tokens": int}

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def has_thinking(self) -> bool:
        return len(self.thinking) > 0

    def __str__(self) -> str:
        if self.has_tool_calls:
            calls = ", ".join(tc.tool_name for tc in self.tool_calls)
            return f"[ToolCalls: {calls}]"
        return self.content


class BaseLLM(ABC):
    """LLM抽象基类，定义通用接口"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "default"):
        self.api_key = api_key
        self.model = model
        self._initialized = False
        logger.info(f"LLM初始化: {self.__class__.__name__}, 模型: {model}")
    
    @abstractmethod
    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None) -> 'LLMResponse':
        """
        发送对话请求

        Args:
            messages: 消息列表
            tools: 工具定义列表（OpenAI function calling 格式），None 表示不使用工具

        Returns:
            LLMResponse: 包含文本内容和/或工具调用

        Raises:
            LLMError: 请求失败时抛出
        """
        pass
    
    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """
        获取文本的向量嵌入
        
        Args:
            text: 输入文本
            
        Returns:
            List[float]: 嵌入向量
            
        Raises:
            LLMError: 请求失败时抛出
        """
        pass
    
    async def stream_chat(self, messages: List[Message]) -> AsyncIterator[str]:
        """
        流式发送对话请求
        
        Args:
            messages: 消息列表
            
        Yields:
            str: LLM响应文本片段
            
        Raises:
            LLMError: 请求失败时抛出
        """
        # 默认实现：先获取完整响应，然后逐字返回
        response = await self.chat(messages)
        text = response.content if isinstance(response, LLMResponse) else str(response)
        for char in text:
            yield char
            import asyncio
            await asyncio.sleep(0.01)  # 控制流式输出速度
    
    async def initialize(self) -> bool:
        """
        初始化LLM连接
        
        Returns:
            bool: 初始化是否成功
        """
        self._initialized = True
        return True
    
    def is_available(self) -> bool:
        """
        检查LLM是否可用
        
        Returns:
            bool: 可用状态
        """
        return self._initialized and self.api_key is not None


class LLMError(Exception):
    """LLM相关异常"""
    
    def __init__(self, message: str, code: str = "LLM_ERROR", details: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
        logger.error(f"LLM错误: {code} - {message}, 详情: {details}")
