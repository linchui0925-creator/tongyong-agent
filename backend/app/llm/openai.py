"""
OpenAI LLM实现 - 支持GPT系列模型的对话和嵌入
使用OpenAI官方API，提供稳定的对话和嵌入服务
"""
from typing import List, Optional, AsyncIterator, Dict, Any
from openai import AsyncOpenAI, APIError, APITimeoutError
from app.llm.base import BaseLLM, LLMError, LLMResponse, ToolCallResult
from app.core.base import Message
from app.llm.request_contract import ModelRequestOptions
import logging
import asyncio
import json

logger = logging.getLogger(__name__)


class OpenAILLM(BaseLLM):
    """OpenAI LLM实现类"""

    DEFAULT_MODEL = "gpt-3.5-turbo"
    DEFAULT_API_BASE = "https://api.openai.com/v1"
    DEFAULT_EMBEDDING_MODEL = "text-embedding-ada-002"
    REQUEST_TIMEOUT = 60  # 请求超时时间（秒）
    MAX_RETRIES = 3  # 最大重试次数

    def __init__(self, api_key: str, model: str = None, embedding_model: str = None):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self._api_base = self.DEFAULT_API_BASE
        self.embedding_model = embedding_model or self.DEFAULT_EMBEDDING_MODEL
        self._client = None
        logger.info(f"OpenAI LLM初始化完成，模型: {self.model}")

    @property
    def api_base(self) -> str:
        return self._api_base

    @api_base.setter
    def api_base(self, value: str):
        api_base = value or self.DEFAULT_API_BASE
        if getattr(self, '_api_base', None) != api_base:
            self._api_base = api_base
            self._client = None  # 触发 client 重建

    def _get_client(self) -> AsyncOpenAI:
        """懒加载 client，当 api_base 变更时自动重建"""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self._api_base,
                timeout=self.REQUEST_TIMEOUT,
            )
        return self._client

    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None, request_options: Optional[ModelRequestOptions] = None, **kwargs) -> LLMResponse:
        """
        发送对话请求到OpenAI

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
            openai_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ]

            logger.info(f"发送请求到OpenAI，消息数: {len(messages)}, 工具数: {len(tools) if tools else 0}")

            # 构建请求参数
            effective_options = request_options or ModelRequestOptions(model=self.model, provider="openai")
            request_kwargs = {
                "model": effective_options.model,
                "messages": openai_messages,
                "temperature": effective_options.controls.temperature if effective_options.controls.temperature is not None else 0.7,
                "max_tokens": effective_options.controls.max_tokens if effective_options.controls.max_tokens is not None else 2000,
                "timeout": self.REQUEST_TIMEOUT,
            }
            if tools:
                request_kwargs["tools"] = tools

            # 发送请求并处理重试
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = await self._get_client().chat.completions.create(
                        **request_kwargs
                    )

                    message = response.choices[0].message
                    reply = message.content or ""

                    # 检查工具调用
                    if message.tool_calls:
                        tool_calls = []
                        for tc in message.tool_calls:
                            try:
                                arguments = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                            except json.JSONDecodeError:
                                arguments = {}
                            tool_calls.append(ToolCallResult(
                                tool_name=tc.function.name,
                                arguments=arguments,
                                tool_call_id=tc.id,
                            ))
                        logger.info(f"OpenAI返回 {len(tool_calls)} 个工具调用: {[tc.tool_name for tc in tool_calls]}")
                        return LLMResponse(content=reply, tool_calls=tool_calls)

                    logger.info(f"OpenAI响应成功，回复长度: {len(reply)}")
                    return LLMResponse(content=reply)

                except APITimeoutError:
                    logger.warning(f"OpenAI请求超时 (尝试 {attempt + 1}/{self.MAX_RETRIES})")
                    if attempt == self.MAX_RETRIES - 1:
                        raise LLMError("请求超时", "TIMEOUT")
                    await asyncio.sleep(2 ** attempt)  # 指数退避

                except APIError as e:
                    logger.warning(f"OpenAI API错误 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    if attempt == self.MAX_RETRIES - 1:
                        raise LLMError(f"API错误: {str(e)}", "API_ERROR", str(e))
                    await asyncio.sleep(2 ** attempt)

        except LLMError:
            raise
        except Exception as e:
            logger.error(f"OpenAI请求失败: {e}")
            raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED", str(e))

    async def stream_chat(self, messages: List[Message], request_options: Optional[ModelRequestOptions] = None) -> AsyncIterator[str]:
        """
        流式发送对话请求到OpenAI

        Args:
            messages: 消息列表

        Yields:
            str: LLM响应文本片段
        """
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")

        try:
            # 转换消息格式
            openai_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ]

            logger.info(f"发送流式请求到OpenAI，消息数: {len(messages)}")

            # 使用流式API
            stream = await self._get_client().chat.completions.create(
                model=(request_options.model if request_options else self.model),
                messages=openai_messages,
                temperature=(request_options.controls.temperature if request_options and request_options.controls.temperature is not None else 0.7),
                max_tokens=(request_options.controls.max_tokens if request_options and request_options.controls.max_tokens is not None else 2000),
                timeout=self.REQUEST_TIMEOUT,
                stream=True
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield content

            logger.info("流式响应完成")

        except Exception as e:
            logger.error(f"OpenAI流式请求失败: {e}")
            raise LLMError(f"流式请求失败: {str(e)}", "STREAM_FAILED", str(e))

    async def get_embedding(self, text: str) -> List[float]:
        """
        获取文本嵌入向量

        Args:
            text: 输入文本

        Returns:
            List[float]: 嵌入向量
        """
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")

        try:
            # 文本预处理
            text = text.replace("\n", " ").strip()
            if len(text) > 8000:
                text = text[:8000]

            logger.debug(f"获取嵌入向量，文本长度: {len(text)}")

            response = await self._get_client().embeddings.create(
                model=self.embedding_model,
                input=text
            )

            embedding = response.data[0].embedding
            logger.debug(f"嵌入向量维度: {len(embedding)}")
            return embedding

        except Exception as e:
            logger.error(f"获取嵌入失败: {e}")
            raise LLMError(f"获取嵌入失败: {str(e)}", "EMBEDDING_FAILED", str(e))

    async def initialize(self) -> bool:
        """
        验证API连接

        Returns:
            bool: 连接是否有效
        """
        try:
            # 发送简单请求验证API可用性
            test_response = await self._get_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1
            )
            self._initialized = True
            logger.info("OpenAI API连接验证成功")
            return True
        except Exception as e:
            logger.error(f"OpenAI API连接验证失败: {e}")
            self._initialized = False
            return False
