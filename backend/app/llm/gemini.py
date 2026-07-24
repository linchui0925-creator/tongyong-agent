"""
Google Gemini LLM实现
支持Gemini系列模型的对话和嵌入
"""
from typing import List, Optional, AsyncIterator, Dict
from app.llm.base import BaseLLM, LLMError, LLMResponse
from app.core.base import Message
from app.llm.request_contract import ModelRequestOptions
import logging
import httpx
import json
import asyncio

logger = logging.getLogger(__name__)


class GeminiLLM(BaseLLM):
    """Google Gemini LLM实现类"""
    
    DEFAULT_MODEL = "gemini-1.5-pro"
    DEFAULT_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    REQUEST_TIMEOUT = 120
    MAX_RETRIES = 3
    
    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self.api_base = self.DEFAULT_API_BASE
        logger.info(f"Google Gemini LLM初始化完成，模型: {self.model}")
    
    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None, request_options: Optional[ModelRequestOptions] = None, **kwargs) -> LLMResponse:
        """发送对话请求到Gemini"""
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")
        
        try:
            effective_options = request_options or ModelRequestOptions(model=self.model, provider="google", api_format="gemini")
            contents = self._convert_messages(messages)
            
            logger.info(f"发送请求到Gemini，消息数: {len(messages)}")
            
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                for attempt in range(self.MAX_RETRIES):
                    try:
                        response = await client.post(
                            f"{self.api_base}/{effective_options.model}:generateContent",
                            headers={
                                "Content-Type": "application/json"
                            },
                            params={"key": self.api_key},
                            json={
                                "contents": contents,
                                "generationConfig": {
                                    "temperature": effective_options.controls.temperature if effective_options.controls.temperature is not None else 0.7,
                                    "maxOutputTokens": effective_options.controls.max_tokens if effective_options.controls.max_tokens is not None else 2048
                                }
                            }
                        )
                        
                        response.raise_for_status()
                        result = response.json()
                        
                        if "candidates" in result and len(result["candidates"]) > 0:
                            candidate = result["candidates"][0]
                            if "content" in candidate and "parts" in candidate["content"]:
                                reply = candidate["content"]["parts"][0].get("text", "")
                                logger.info(f"Gemini响应成功，回复长度: {len(reply)}")
                                return LLMResponse(content=reply)
                        
                        raise LLMError("响应格式错误", "INVALID_RESPONSE", result)
                            
                    except httpx.TimeoutException:
                        logger.warning(f"Gemini请求超时 (尝试 {attempt + 1}/{self.MAX_RETRIES})")
                        if attempt == self.MAX_RETRIES - 1:
                            raise LLMError("请求超时", "TIMEOUT")
                        await asyncio.sleep(2 ** attempt)
                        
                    except Exception as e:
                        logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                        if attempt == self.MAX_RETRIES - 1:
                            raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED")
                        await asyncio.sleep(2 ** attempt)
                            
        except LLMError:
            raise
        except Exception as e:
            logger.error(f"Gemini请求失败: {e}")
            raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED", str(e))
    
    async def get_embedding(self, text: str) -> List[float]:
        """获取文本嵌入向量"""
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")
        
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                response = await client.post(
                    f"{self.api_base}/embedding-001:batchEmbedContents",
                    headers={"Content-Type": "application/json"},
                    params={"key": self.api_key},
                    json={
                        "requests": [{
                            "model": f"{self.api_base}/embedding-001",
                            "content": {"parts": [{"text": text}]}
                        }]
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                if "embeddings" in result and len(result["embeddings"]) > 0:
                    embedding = result["embeddings"][0]["values"]
                    logger.debug(f"嵌入向量维度: {len(embedding)}")
                    return embedding
                    
                raise LLMError("响应格式错误", "INVALID_RESPONSE", result)
                    
        except httpx.HTTPStatusError as e:
            logger.error(f"获取嵌入失败HTTP错误: {e.response.status_code}")
            return self._generate_fallback_embedding(text)
        except Exception as e:
            logger.error(f"获取嵌入失败: {e}")
            return self._generate_fallback_embedding(text)
    
    async def stream_chat(self, messages: List[Message], request_options: Optional[ModelRequestOptions] = None) -> AsyncIterator[str]:
        """流式发送对话请求到Gemini"""
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")
        
        try:
            contents = self._convert_messages(messages)
            
            logger.info(f"发送流式请求到Gemini，消息数: {len(messages)}")
            
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{self.api_base}/{self.model}:generateContent",
                    headers={"Content-Type": "application/json"},
                    params={"key": self.api_key, "alt": "sse"},
                    json={
                        "contents": contents,
                        "generationConfig": {
                            "temperature": 0.7,
                            "maxOutputTokens": 2048
                        }
                    }
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                data = json.loads(line[5:])
                                if "candidates" in data:
                                    candidate = data["candidates"][0]
                                    if "content" in candidate and "parts" in candidate["content"]:
                                        text = candidate["content"]["parts"][0].get("text", "")
                                        if text:
                                            yield text
                            except json.JSONDecodeError:
                                continue
            
            logger.info("Gemini流式响应完成")
            
        except Exception as e:
            logger.error(f"Gemini流式请求失败: {e}")
            raise LLMError(f"流式请求失败: {str(e)}", "STREAM_FAILED", str(e))
    
    def _convert_messages(self, messages: List[Message]) -> List[dict]:
        """转换消息格式"""
        contents = []
        for msg in messages:
            if msg.role == "system":
                continue
            contents.append({
                "role": "model" if msg.role == "assistant" else "user",
                "parts": [{"text": msg.content}]
            })
        return contents
    
    def _generate_fallback_embedding(self, text: str) -> List[float]:
        """生成降级向量"""
        import hashlib
        
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = []
        for i in range(768):
            byte_val = hash_bytes[i % len(hash_bytes)]
            embedding.append((byte_val / 128.0) - 1.0)
        
        return embedding
    
    async def initialize(self) -> bool:
        """验证API连接"""
        try:
            test_result = await self.chat([Message(role="user", content="test")])
            self._initialized = True
            logger.info("Gemini API连接验证成功")
            return True
        except Exception as e:
            logger.error(f"Gemini API连接验证失败: {e}")
            self._initialized = False
            return False
