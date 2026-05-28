"""
智谱AI ChatGLM LLM实现
支持ChatGLM系列模型的对话
"""
from typing import List, AsyncIterator, Optional, Dict
from app.llm.base import BaseLLM, LLMError, LLMResponse
from app.core.base import Message
import logging
import httpx
import json
import asyncio

logger = logging.getLogger(__name__)


class ChatGLMLLM(BaseLLM):
    """智谱AI ChatGLM LLM实现类"""
    
    DEFAULT_MODEL = "glm-4"
    DEFAULT_API_BASE = "https://open.bigmodel.cn/api/paas/v4"
    REQUEST_TIMEOUT = 120
    MAX_RETRIES = 3
    
    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self.api_base = self.DEFAULT_API_BASE
        logger.info(f"ChatGLM LLM初始化完成，模型: {self.model}")
    
    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None) -> LLMResponse:
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")
        
        try:
            chat_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
            
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                response = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "messages": chat_messages}
                )
                response.raise_for_status()
                result = response.json()
                
                if "choices" in result and len(result["choices"]) > 0:
                    return LLMResponse(content=result["choices"][0]["message"]["content"])
                raise LLMError("响应格式错误", "INVALID_RESPONSE", result)
        except Exception as e:
            logger.error(f"ChatGLM请求失败: {e}")
            raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED")
    
    async def get_embedding(self, text: str) -> List[float]:
        return self._generate_fallback_embedding(text)
    
    async def stream_chat(self, messages: List[Message]) -> AsyncIterator[str]:
        response = await self.chat(messages)
        text = response.content if isinstance(response, LLMResponse) else str(response)
        for char in text:
            yield char
            await asyncio.sleep(0.01)
    
    def _generate_fallback_embedding(self, text: str) -> List[float]:
        import hashlib
        hash_bytes = hashlib.sha256(text.encode()).digest()
        return [(hash_bytes[i % len(hash_bytes)] / 128.0) - 1.0 for i in range(1024)]
    
    async def initialize(self) -> bool:
        try:
            await self.chat([Message(role="user", content="test")])
            self._initialized = True
            return True
        except:
            self._initialized = False
            return False
