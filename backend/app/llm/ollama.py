"""
Ollama 本地LLM实现
支持本地Ollama服务运行的模型
"""
from typing import List, AsyncIterator, Optional, Dict
from app.llm.base import BaseLLM, LLMError, LLMResponse
from app.core.base import Message
import logging
import httpx
import asyncio

logger = logging.getLogger(__name__)


class OllamaLLM(BaseLLM):
    DEFAULT_MODEL = "llama3"
    DEFAULT_API_BASE = "http://localhost:11434/api"
    
    def __init__(self, api_key: str = None, model: str = None):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self.api_base = self.DEFAULT_API_BASE
    
    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None) -> LLMResponse:
        chat_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
        
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.api_base}/chat",
                json={"model": self.model, "messages": chat_messages, "stream": False}
            )
            response.raise_for_status()
            result = response.json()
            if "message" in result:
                return LLMResponse(content=result["message"]["content"])
            raise LLMError("响应格式错误", "INVALID_RESPONSE")
    
    async def get_embedding(self, text: str) -> List[float]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.api_base}/embeddings",
                json={"model": self.model, "prompt": text}
            )
            response.raise_for_status()
            result = response.json()
            if "embedding" in result:
                return result["embedding"]
        
        import hashlib
        hash_bytes = hashlib.sha256(text.encode()).digest()
        return [(hash_bytes[i % len(hash_bytes)] / 128.0) - 1.0 for i in range(1024)]
    
    async def stream_chat(self, messages: List[Message]) -> AsyncIterator[str]:
        chat_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
        
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.api_base}/chat",
                json={"model": self.model, "messages": chat_messages, "stream": True}
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            import json
                            data = json.loads(line)
                            if "message" in data and "content" in data["message"]:
                                yield data["message"]["content"]
                        except:
                            continue
    
    async def initialize(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.api_base}/tags")
                self._initialized = response.status_code == 200
                return self._initialized
        except:
            self._initialized = False
            return False
