"""
通义千问LLM实现 - 支持阿里云通义千问模型的对话和嵌入
使用DashScope API，提供中文对话和嵌入服务
"""
from typing import List, Optional, AsyncIterator, Dict, Any, Union
from app.llm.base import BaseLLM, LLMError, LLMResponse, ToolCallResult
from app.core.base import Message
from app.llm.request_contract import ModelRequestOptions
import logging
import httpx
import json
import asyncio

logger = logging.getLogger(__name__)


class TongyiLLM(BaseLLM):
    """通义千问LLM实现类"""
    
    DEFAULT_MODEL = "qwen-plus"
    DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/api/v1"
    COMPATIBLE_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    REQUEST_TIMEOUT = 60
    MAX_RETRIES = 3
    
    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self.api_base = self.DEFAULT_API_BASE
        logger.info(f"通义千问LLM初始化完成，模型: {self.model}")
    
    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None, request_options: Optional[ModelRequestOptions] = None, **kwargs) -> LLMResponse:
        """
        发送对话请求到通义千问

        当提供 tools 时，使用兼容模式 API（支持 function calling）；
        否则使用原生 API。

        Args:
            messages: 消息列表
            tools: 工具定义列表（OpenAI function calling 格式）

        Returns:
            LLMResponse: 包含文本和/或工具调用
        """
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")

        try:
            # 转换消息格式
            api_messages = []
            for msg in messages:
                if msg.role == "tool":
                    try:
                        tool_data = json.loads(msg.content)
                        api_messages.append({
                            "role": "tool",
                            "content": tool_data.get("content", msg.content),
                            "tool_call_id": tool_data.get("tool_call_id", "")
                        })
                    except (json.JSONDecodeError, AttributeError):
                        api_messages.append({"role": "tool", "content": msg.content})
                elif msg.role == "assistant":
                    try:
                        asst_data = json.loads(msg.content)
                        if "tool_calls" in asst_data:
                            api_messages.append({
                                "role": "assistant",
                                "content": asst_data.get("content", ""),
                                "tool_calls": asst_data["tool_calls"]
                            })
                        else:
                            api_messages.append({"role": "assistant", "content": msg.content})
                    except (json.JSONDecodeError, AttributeError):
                        api_messages.append({"role": "assistant", "content": msg.content})
                else:
                    api_messages.append({"role": msg.role, "content": msg.content})

            effective_options = request_options or ModelRequestOptions(model=self.model, provider="tongyi", api_format="chat_completions")
            use_tools = bool(tools)
            logger.info(f"发送请求到通义千问，消息数: {len(messages)}, 工具数: {len(tools) if tools else 0}, 兼容模式: {use_tools}")

            if use_tools:
                return await self._chat_compatible(api_messages, tools, effective_options)
            else:
                return await self._chat_native(api_messages, effective_options)

        except LLMError:
            raise
        except Exception as e:
            logger.error(f"通义千问请求失败: {e}")
            raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED", str(e))

    async def _chat_compatible(self, messages: List[Dict], tools: List[Dict], request_options: ModelRequestOptions) -> LLMResponse:
        """使用兼容模式 API（支持 function calling）"""
        url = f"{self.COMPATIBLE_API_BASE}/chat/completions"
        request_body = {
            "model": request_options.model,
            "messages": messages,
            "tools": tools,
            "temperature": request_options.controls.temperature if request_options.controls.temperature is not None else 0.7,
            "max_tokens": request_options.controls.max_tokens if request_options.controls.max_tokens is not None else 2000
        }

        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = await client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json=request_body
                    )
                    response.raise_for_status()
                    result = response.json()

                    choices = result.get("choices", [])
                    if not choices:
                        raise LLMError("响应格式错误", "INVALID_RESPONSE", result)

                    message = choices[0].get("message", {})
                    content = message.get("content", "") or ""

                    # 修复 (W4-2 2026-06-09): 把 DashScope usage 灌进 LLMResponse,
                    #   langchain_adapter._agenerate 才能挂到 AIMessage.usage_metadata,
                    #   on_chat_model_end 才拿得到 token 数, TokenUsageBar 才不显示 0/0。
                    # OpenAI 兼容格式: {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
                    raw_usage = result.get("usage") or {}
                    if raw_usage:
                        usage = {
                            "input_tokens": raw_usage.get("prompt_tokens", 0),
                            "output_tokens": raw_usage.get("completion_tokens", 0),
                            "total_tokens": raw_usage.get("total_tokens", 0),
                        }
                    else:
                        usage = {}

                    # 检查工具调用
                    tool_calls_raw = message.get("tool_calls", [])
                    if tool_calls_raw:
                        tool_calls = []
                        for tc in tool_calls_raw:
                            func = tc.get("function", {})
                            name = func.get("name", "")
                            args_str = func.get("arguments", "{}")
                            try:
                                arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                            except json.JSONDecodeError:
                                arguments = {}
                            tool_calls.append(ToolCallResult(
                                tool_name=name,
                                arguments=arguments,
                                tool_call_id=tc.get("id", "")
                            ))
                        logger.info(f"通义千问返回 {len(tool_calls)} 个工具调用: {[tc.tool_name for tc in tool_calls]}")
                        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage)

                    logger.info(f"通义千问兼容模式响应成功，回复长度: {len(content)}, usage={usage}")
                    return LLMResponse(content=content, usage=usage)

                except httpx.TimeoutException:
                    logger.warning(f"兼容模式请求超时 (尝试 {attempt + 1}/{self.MAX_RETRIES})")
                    if attempt == self.MAX_RETRIES - 1:
                        raise LLMError("请求超时", "TIMEOUT")
                    await asyncio.sleep(2 ** attempt)

                except httpx.HTTPStatusError as e:
                    logger.warning(f"兼容模式HTTP错误 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    if attempt == self.MAX_RETRIES - 1:
                        raise LLMError(f"HTTP错误: {e.response.status_code}", "HTTP_ERROR")
                    await asyncio.sleep(2 ** attempt)

                except LLMError:
                    raise
                except Exception as e:
                    logger.warning(f"兼容模式请求失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    if attempt == self.MAX_RETRIES - 1:
                        raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED")
                    await asyncio.sleep(2 ** attempt)

    async def _chat_native(self, messages: List[Dict], request_options: ModelRequestOptions) -> LLMResponse:
        """使用原生 API（不支持 function calling）"""
        url = f"{self.api_base}/services/aigc/text-generation/generation"
        request_body = {
            "model": self.model,
            "input": {"messages": messages},
            "parameters": {
                "temperature": request_options.controls.temperature if request_options.controls.temperature is not None else 0.7,
                "max_tokens": request_options.controls.max_tokens if request_options.controls.max_tokens is not None else 2000
            }
        }

        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = await client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json=request_body
                    )
                    response.raise_for_status()
                    result = response.json()

                    output = result.get("output", {})
                    choices = output.get("choices", [])

                    # 修复 (W4-2): 原生模式也灌 usage (字段位置相同: result["usage"])
                    raw_usage = result.get("usage") or {}
                    if raw_usage:
                        usage = {
                            "input_tokens": raw_usage.get("prompt_tokens", 0) or raw_usage.get("input_tokens", 0),
                            "output_tokens": raw_usage.get("completion_tokens", 0) or raw_usage.get("output_tokens", 0),
                            "total_tokens": raw_usage.get("total_tokens", 0),
                        }
                    else:
                        usage = {}

                    if choices:
                        content = choices[0].get("message", {}).get("content", "") or ""
                        logger.info(f"通义千问原生API响应成功，回复长度: {len(content)}, usage={usage}")
                        return LLMResponse(content=content, usage=usage)

                    if "text" in output:
                        return LLMResponse(content=output["text"], usage=usage)

                    raise LLMError("响应格式错误", "INVALID_RESPONSE", result)

                except httpx.TimeoutException:
                    logger.warning(f"原生API请求超时 (尝试 {attempt + 1}/{self.MAX_RETRIES})")
                    if attempt == self.MAX_RETRIES - 1:
                        raise LLMError("请求超时", "TIMEOUT")
                    await asyncio.sleep(2 ** attempt)

                except httpx.HTTPStatusError as e:
                    logger.warning(f"原生API HTTP错误 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    if attempt == self.MAX_RETRIES - 1:
                        raise LLMError(f"HTTP错误: {e.response.status_code}", "HTTP_ERROR")
                    await asyncio.sleep(2 ** attempt)

                except LLMError:
                    raise
                except Exception as e:
                    logger.warning(f"原生API请求失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    if attempt == self.MAX_RETRIES - 1:
                        raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED")
                    await asyncio.sleep(2 ** attempt)
    
    async def get_embedding(self, text: str) -> List[float]:
        """获取文本嵌入向量"""
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")
        
        try:
            text = text.replace("\n", " ").strip()
            if len(text) > 8000:
                text = text[:8000]
            
            logger.debug(f"获取嵌入向量，文本长度: {len(text)}")
            
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                base = self.COMPATIBLE_API_BASE
                response = await client.post(
                    f"{base}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "text-embedding-v3",
                        "input": text,
                        "dimensions": 1024
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                if "data" in result and len(result["data"]) > 0:
                    embedding = result["data"][0]["embedding"]
                    logger.debug(f"嵌入向量维度: {len(embedding)}")
                    return embedding
                else:
                    logger.warning(f"嵌入响应格式: {result}")
                    raise LLMError("响应格式错误", "INVALID_RESPONSE", result)
                    
        except httpx.HTTPStatusError as e:
            logger.error(f"获取嵌入失败HTTP错误: {e.response.status_code}")
            logger.warning("嵌入API不可用，返回降级向量")
            return self._generate_fallback_embedding(text)
        except Exception as e:
            logger.error(f"获取嵌入失败: {e}")
            logger.warning("嵌入获取失败，返回降级向量")
            return self._generate_fallback_embedding(text)
    
    def _generate_fallback_embedding(self, text: str) -> List[float]:
        """
        生成降级向量（当嵌入API不可用时使用）
        基于文本长度和字符生成简单的伪向量
        
        Args:
            text: 输入文本
            
        Returns:
            List[float]: 降级向量
        """
        import hashlib
        
        # 使用文本的hash生成一个确定性的向量
        hash_bytes = hashlib.sha256(text.encode()).digest()
        
        # 生成1024维向量（与ChromaDB集合维度匹配）
        embedding = []
        for i in range(1024):
            # 使用hash字节循环生成值
            byte_val = hash_bytes[i % len(hash_bytes)]
            # 归一化到-1到1之间
            embedding.append((byte_val / 128.0) - 1.0)
        
        logger.debug(f"生成降级向量，维度: {len(embedding)}")
        return embedding
    
    async def initialize(self) -> bool:
        """
        验证API连接
        
        Returns:
            bool: 连接是否有效
        """
        try:
            test_result = await self.chat([
                Message(role="user", content="test")
            ])
            self._initialized = True
            logger.info("通义千问API连接验证成功")
            return True
        except Exception as e:
            logger.error(f"通义千问API连接验证失败: {e}")
            self._initialized = False
            return False
