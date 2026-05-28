"""
Anthropic Claude LLM实现
支持Claude系列模型的对话
"""
from typing import List, Optional, AsyncIterator, Dict
from app.llm.base import BaseLLM, LLMError, LLMResponse
from app.core.base import Message
import logging
import httpx
import json
import asyncio

logger = logging.getLogger(__name__)


class AnthropicLLM(BaseLLM):
    """Anthropic Claude LLM实现类"""
    
    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    DEFAULT_API_BASE = "https://api.anthropic.com/v1"
    REQUEST_TIMEOUT = 120
    MAX_RETRIES = 3
    
    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self._api_base = self.DEFAULT_API_BASE
        logger.info(f"Anthropic Claude LLM初始化完成，模型: {self.model}")

    @property
    def api_base(self) -> str:
        return self._api_base

    @api_base.setter
    def api_base(self, value: str):
        self._api_base = value or self.DEFAULT_API_BASE
    
    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None) -> LLMResponse:
        """发送对话请求到Claude"""
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")
        
        try:
            anthropic_messages = self._convert_messages(messages)
            
            logger.info(f"发送请求到Claude，消息数: {len(messages)}")
            
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                for attempt in range(self.MAX_RETRIES):
                    try:
                        response = await client.post(
                            f"{self.api_base}/messages",
                            headers={
                                "x-api-key": self.api_key,
                                "anthropic-version": "2023-06-01",
                                "content-type": "application/json"
                            },
                            json={
                                "model": self.model,
                                "messages": anthropic_messages,
                                "max_tokens": 4096
                            }
                        )
                        
                        response.raise_for_status()
                        result = response.json()
                        
                        if "content" in result and len(result["content"]) > 0:
                            reply = result["content"][0].get("text", "")
                            logger.info(f"Claude响应成功，回复长度: {len(reply)}")
                            return LLMResponse(content=reply)
                        else:
                            raise LLMError("响应格式错误", "INVALID_RESPONSE", result)
                            
                    except httpx.TimeoutException:
                        logger.warning(f"Claude请求超时 (尝试 {attempt + 1}/{self.MAX_RETRIES})")
                        if attempt == self.MAX_RETRIES - 1:
                            raise LLMError("请求超时", "TIMEOUT")
                        await asyncio.sleep(2 ** attempt)
                        
                    except httpx.HTTPStatusError as e:
                        logger.warning(f"HTTP错误 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                        if attempt == self.MAX_RETRIES - 1:
                            error_detail = e.response.text if e.response else ""
                            raise LLMError(f"HTTP错误: {e.response.status_code} - {error_detail}", "HTTP_ERROR")
                        await asyncio.sleep(2 ** attempt)
                        
                    except Exception as e:
                        logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                        if attempt == self.MAX_RETRIES - 1:
                            raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED")
                        await asyncio.sleep(2 ** attempt)
                            
        except LLMError:
            raise
        except Exception as e:
            logger.error(f"Claude请求失败: {e}")
            raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED", str(e))
    
    async def get_embedding(self, text: str) -> List[float]:
        """Claude不提供嵌入API，返回降级向量"""
        logger.warning("Claude不提供嵌入API，使用降级向量")
        return self._generate_fallback_embedding(text)
    
    async def stream_chat(self, messages: List[Message]) -> AsyncIterator[str]:
        """流式发送对话请求到Claude"""
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")
        
        try:
            anthropic_messages = self._convert_messages(messages)
            
            logger.info(f"发送流式请求到Claude，消息数: {len(messages)}")
            
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{self.api_base}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": anthropic_messages,
                        "max_tokens": 4096,
                        "stream": True
                    }
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                data = json.loads(line[5:])
                                if data.get("type") == "content_block_delta":
                                    text = data.get("delta", {}).get("text", "")
                                    if text:
                                        yield text
                            except json.JSONDecodeError:
                                continue
            
            logger.info("Claude流式响应完成")
            
        except Exception as e:
            logger.error(f"Claude流式请求失败: {e}")
            raise LLMError(f"流式请求失败: {str(e)}", "STREAM_FAILED", str(e))
    
    def _convert_messages(self, messages: List[Message]) -> List[dict]:
        """转换消息格式"""
        converted = []
        for msg in messages:
            if msg.role == "system":
                converted.append({
                    "role": "user",
                    "content": f"[系统提示] {msg.content}"
                })
            else:
                converted.append({
                    "role": msg.role,
                    "content": msg.content
                })
        return converted
    
    def _generate_fallback_embedding(self, text: str) -> List[float]:
        """生成降级向量"""
        import hashlib
        
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = []
        for i in range(1024):
            byte_val = hash_bytes[i % len(hash_bytes)]
            embedding.append((byte_val / 128.0) - 1.0)
        
        logger.debug(f"生成降级向量，维度: {len(embedding)}")
        return embedding
    
    async def initialize(self) -> bool:
        """验证API连接"""
        try:
            test_result = await self.chat([Message(role="user", content="test")])
            self._initialized = True
            logger.info("Claude API连接验证成功")
            return True
        except Exception as e:
            logger.error(f"Claude API连接验证失败: {e}")
            self._initialized = False
            return False
