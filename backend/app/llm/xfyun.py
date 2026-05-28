"""
讯飞星火 LLM实现
支持Spark系列模型的对话
"""
from typing import List, AsyncIterator, Optional, Dict
from app.llm.base import BaseLLM, LLMError, LLMResponse
from app.core.base import Message
import logging
import httpx
import asyncio

logger = logging.getLogger(__name__)


class XfyunLLM(BaseLLM):
    DEFAULT_MODEL = "spark-v4.0"
    DEFAULT_API_BASE = "https://spark-api.xf-yun.com/v4.0/chat"
    
    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self.api_base = self.DEFAULT_API_BASE
    
    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None) -> LLMResponse:
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")
        
        chat_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
        
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                self.api_base,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "messages": chat_messages}
            )
            response.raise_for_status()
            result = response.json()
            if "choices" in result:
                return LLMResponse(content=result["choices"][0]["message"]["content"])
            raise LLMError("响应格式错误", "INVALID_RESPONSE")
    
    async def get_embedding(self, text: str) -> List[float]:
        import hashlib
        hash_bytes = hashlib.sha256(text.encode()).digest()
        return [(hash_bytes[i % len(hash_bytes)] / 128.0) - 1.0 for i in range(1024)]
    
    async def stream_chat(self, messages: List[Message]) -> AsyncIterator[str]:
        response = await self.chat(messages)
        text = response.content if isinstance(response, LLMResponse) else str(response)
        for char in text:
            yield char
            await asyncio.sleep(0.01)
    
    async def initialize(self) -> bool:
        try:
            await self.chat([Message(role="user", content="test")])
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"讯飞星火 API连接验证失败: {e}")
            self._initialized = False
            return False
