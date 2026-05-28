"""
OpenAICompatibleLLM - 通用 OpenAI 兼容接口

适用于任何兼容 OpenAI Chat Completions API 格式的提供商：
- DeepSeek / Yi / MiniMax / Moonshot / Stepfun / 硅基流动 / together.ai 等

通过配置 api_base 即可适配，无需为每个提供商单独编写实现。
"""

import json
import logging
from typing import List, Optional, AsyncIterator, Dict

import httpx

from app.llm.base import BaseLLM, LLMError, LLMResponse, ToolCallResult
from app.core.base import Message

logger = logging.getLogger(__name__)


class OpenAICompatibleLLM(BaseLLM):
    """
    通用 OpenAI 兼容接口 LLM

    任何兼容 OpenAI /v1/chat/completions 格式的 API 均可使用此类。
    通过 api_base 区分不同提供商，默认模型由各提供商配置决定。

    支持：对话、流式、工具调用（function calling）、嵌入向量。
    """

    DEFAULT_API_BASE = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-3.5-turbo"
    REQUEST_TIMEOUT = 120
    MAX_RETRIES = 3

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model or self.DEFAULT_MODEL)
        self.api_base = self.DEFAULT_API_BASE

    @staticmethod
    def _merge_system_messages(messages: List[Dict]) -> List[Dict]:
        """合并所有 system 消息为一条（某些 API 如 MiniMax 不支持多条 system 消息）"""
        merged = []
        system_parts = []
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                merged.append(msg)
        if system_parts:
            merged.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})
        return merged

    @staticmethod
    def _normalize_messages(messages: List[Dict]) -> List[Dict]:
        """规范化消息格式，修复 agent 层 JSON 编码导致的不兼容问题

        agent 层将 tool_calls 和 tool 结果 JSON 编码到 content 字段中，
        但部分 API（如 MiniMax）严格要求 OpenAI 标准格式：
        - assistant 的 tool_calls 必须是顶级字段
        - tool 消息必须有 tool_call_id 顶级字段
        """
        normalized = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")

            # 尝试修复 assistant 消息中嵌入的 tool_calls
            if role == "assistant" and content:
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and "tool_calls" in parsed:
                        new_msg = {
                            "role": "assistant",
                            "content": parsed.get("content") or "",
                            "tool_calls": parsed["tool_calls"],
                        }
                        normalized.append(new_msg)
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass

            # 尝试修复 tool 消息中嵌入的 tool_call_id
            if role == "tool" and content:
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and "tool_call_id" in parsed:
                        new_msg = {
                            "role": "tool",
                            "tool_call_id": parsed["tool_call_id"],
                            "content": parsed.get("content", ""),
                        }
                        normalized.append(new_msg)
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
                # JSON 损坏：从原始 content 字符串中用正则提取 tool_call_id
                import re
                tc_match = re.search(r'"tool_call_id"\s*:\s*"([^"]+)"', content)
                if tc_match:
                    normalized.append({
                        "role": "tool",
                        "tool_call_id": tc_match.group(1),
                        "content": content,
                    })
                    continue
                # 兜底：保留原消息，让 API 处理错误
                normalized.append(msg)
                continue

            # user/system 消息直接保留
            normalized.append(msg)
        return normalized

    @staticmethod
    def _decode_json_response(resp: httpx.Response) -> Dict:
        """稳健解析 JSON 响应，兼容 BOM、空响应和部分兼容 API 的脏前缀。"""
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raw_text = resp.text or ""
            preview = raw_text[:500]
            logger.warning(
                "OpenAI-compatible JSON解析失败: status=%s content-type=%s preview=%r",
                resp.status_code,
                resp.headers.get("content-type", ""),
                preview,
            )

            cleaned = raw_text.lstrip("\ufeff \t\r\n")
            if not cleaned:
                raise LLMError("响应体为空，无法解析模型返回", "EMPTY_RESPONSE") from e

            json_start = cleaned.find("{")
            json_end = cleaned.rfind("}")
            if json_start != -1 and json_end > json_start:
                candidate = cleaned[json_start:json_end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

            raise LLMError("响应不是有效 JSON", "INVALID_JSON_RESPONSE", preview) from e

    # ── 对话 ──────────────────────────────────────────────

    async def chat(self, messages: List[Message], tools: Optional[List[Dict]] = None) -> LLMResponse:
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")

        openai_messages = self._normalize_messages(
            self._merge_system_messages(
                [{"role": m.role, "content": m.content} for m in messages]
            )
        )

        body = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": getattr(self, "temperature", 0.7),
            "max_tokens": getattr(self, "max_tokens", 2000),
        }
        if tools:
            body["tools"] = tools

        # Debug: 记录发送的消息格式（关键：检查 tool_call_id 是否存在）
        logger.info(f"[LLM Debug] 发送 {len(openai_messages)} 条消息")
        for i, msg in enumerate(openai_messages[:10]):
            role = msg.get('role', 'unknown')
            # 显示 role + 是否有 tool_call_id + tool_call_id 值的前10字符
            tc_id = msg.get('tool_call_id', '')
            tc_id_display = tc_id[:10] + '...' if tc_id and len(tc_id) > 10 else tc_id
            logger.info(f"  消息{i}: role={role}, tool_call_id={repr(tc_id_display)}")
            # 对于 assistant，显示 content 前100字符
            if role == 'assistant':
                content = msg.get('content', '') or ''
                logger.info(f"    content_preview: {content[:100]}")

        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                    resp = await client.post(
                        f"{self.api_base}/chat/completions",
                        headers=self._headers(),
                        json=body,
                    )
                    resp.raise_for_status()
                    result = self._decode_json_response(resp)
                    return self._parse_response(result)

            except httpx.TimeoutException:
                logger.warning(f"请求超时 (尝试 {attempt + 1}/{self.MAX_RETRIES})")
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError("请求超时", "TIMEOUT")
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP错误 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e.response.status_code} - {e.response.text[:300]}")
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError(f"HTTP错误: {e.response.status_code}", "HTTP_ERROR", str(e))
            except Exception as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                if attempt == self.MAX_RETRIES - 1:
                    raise LLMError(f"请求失败: {str(e)}", "REQUEST_FAILED")

    # ── 流式 ──────────────────────────────────────────────

    async def stream_chat(self, messages: List[Message]) -> AsyncIterator[str]:
        if not self.api_key:
            raise LLMError("API密钥未设置", "MISSING_API_KEY")

        openai_messages = self._normalize_messages(
            self._merge_system_messages(
                [{"role": m.role, "content": m.content} for m in messages]
            )
        )

        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.api_base}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": openai_messages,
                    "temperature": getattr(self, "temperature", 0.7),
                    "max_tokens": getattr(self, "max_tokens", 2000),
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data:") and line != "data: [DONE]":
                        try:
                            data = json.loads(line[5:])
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except json.JSONDecodeError:
                            continue

    # ── 嵌入向量 ──────────────────────────────────────────

    async def get_embedding(self, text: str) -> List[float]:
        if not self.api_key:
            return self._generate_fallback_embedding(text)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.api_base}/embeddings",
                    headers=self._headers(),
                    json={"model": self._embedding_model(), "input": text},
                )
                resp.raise_for_status()
                result = self._decode_json_response(resp)
                if "data" in result and len(result["data"]) > 0:
                    return result["data"][0]["embedding"]
        except Exception as e:
            logger.warning(f"嵌入向量获取失败: {e}")
        return self._generate_fallback_embedding(text)

    # ── 连接验证 ──────────────────────────────────────────

    async def initialize(self) -> bool:
        try:
            resp = await self.chat([Message(role="user", content="hi")])
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"API连接验证失败: {e}")
            self._initialized = False
            return False

    # ── 内部方法 ──────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _embedding_model(self) -> str:
        """嵌入模型名称，可由子类覆盖"""
        return "text-embedding-ada-002"

    def _parse_response(self, result: Dict) -> LLMResponse:
        """解析 OpenAI 格式的响应"""
        choices = result.get("choices", [])
        if not choices:
            raise LLMError("响应格式错误", "INVALID_RESPONSE", result)

        message = choices[0].get("message", {})
        content = message.get("content") or ""

        # 工具调用
        tool_calls_raw = message.get("tool_calls", [])
        if tool_calls_raw:
            tool_calls = []
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(ToolCallResult(
                    tool_name=func.get("name", ""),
                    arguments=arguments,
                    tool_call_id=tc.get("id", ""),
                ))
            return LLMResponse(content=content, tool_calls=tool_calls)

        return LLMResponse(content=content)

    def _parse_response_with_thinking(self, result: Dict) -> LLMResponse:
        """解析包含 thinking 内容的响应（如 DeepSeek-R1）"""
        choices = result.get("choices", [])
        if not choices:
            raise LLMError("响应格式错误", "INVALID_RESPONSE", result)

        message = choices[0].get("message", {})
        content = message.get("content") or ""

        # 尝试从 content 中提取 <think>...晖 部分
        thinking_chunks = []
        import re

        # 首先尝试匹配完整的 <think>...晖 对
        think_match = re.search(r'<think>([\s\S]*?)晖', content)
        if think_match:
            thinking_text = think_match.group(1).strip()
            # 移除 thinking 部分
            content = re.sub(r'<think>[\s\S]*?晖', '', content, count=1).strip()

            # 将 thinking 内容切分成小块用于流式展示
            lines_text = thinking_text.split('\n')
            current_chunk = ""
            for line in lines_text:
                if len(current_chunk) + len(line) > 100:
                    if current_chunk:
                        thinking_chunks.append(current_chunk)
                    current_chunk = line
                else:
                    current_chunk += ('\n' if current_chunk else '') + line
            if current_chunk:
                thinking_chunks.append(current_chunk)

        # 工具调用
        tool_calls_raw = message.get("tool_calls", [])
        if tool_calls_raw:
            tool_calls = []
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(ToolCallResult(
                    tool_name=func.get("name", ""),
                    arguments=arguments,
                    tool_call_id=tc.get("id", ""),
                ))
            return LLMResponse(content=content, tool_calls=tool_calls, thinking=thinking_chunks)

        return LLMResponse(content=content, thinking=thinking_chunks)

    def _generate_fallback_embedding(self, text: str) -> List[float]:
        import hashlib
        hash_bytes = hashlib.sha256(text.encode()).digest()
        return [(hash_bytes[i % len(hash_bytes)] / 128.0) - 1.0 for i in range(1024)]


# ═══════════════════════════════════════════════════════════
# 各提供商子类（自动配置 api_base 和默认模型）
# ═══════════════════════════════════════════════════════════


class DeepSeekLLM(OpenAICompatibleLLM):
    DEFAULT_API_BASE = "https://api.deepseek.com/v1"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model)
        self.api_base = self.DEFAULT_API_BASE

    def _embedding_model(self) -> str:
        return "deepseek-embedder"

    def _parse_response(self, result: Dict) -> LLMResponse:
        """DeepSeek 使用带 thinking 的解析方法（支持 R1 等推理模型）"""
        return self._parse_response_with_thinking(result)


class YiLLM(OpenAICompatibleLLM):
    DEFAULT_API_BASE = "https://api.lingyiwanwu.com/v1"
    DEFAULT_MODEL = "yi-large"

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model)
        self.api_base = self.DEFAULT_API_BASE


class MiniMaxLLM(OpenAICompatibleLLM):
    """MiniMax（稀宇科技）"""
    DEFAULT_API_BASE = "https://api.minimax.chat/v1"
    DEFAULT_MODEL = "MiniMax-Text-01"

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model)
        self.api_base = self.DEFAULT_API_BASE

    def _parse_response(self, result: Dict) -> LLMResponse:
        """解析响应，清理 Qwen 风格的 thinking 标签后再解析"""
        import re

        choices = result.get("choices", [])
        if not choices:
            raise LLMError("响应格式错误", "INVALID_RESPONSE", result)

        message = choices[0].get("message", {})
        content = message.get("content") or ""

        # MiniMax 模型可能输出 Qwen 风格的 <|im_start|>...<|im_end|> 标记
        # 或 <think>...晖 思考标签，直接清理掉
        content = re.sub(r'<\|im_start\|[^|]*\|[^>]*>[\s\S]*?<\|im_end\|>', '', content)
        content = re.sub(r'<think>[\s\S]*?晖', '', content)
        content = content.strip()

        # 工具调用
        tool_calls_raw = message.get("tool_calls", [])
        if tool_calls_raw:
            tool_calls = []
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(ToolCallResult(
                    tool_name=func.get("name", ""),
                    arguments=arguments,
                    tool_call_id=tc.get("id", ""),
                ))
            return LLMResponse(content=content, tool_calls=tool_calls)

        return LLMResponse(content=content)


class MoonshotLLM(OpenAICompatibleLLM):
    """Moonshot / 月之暗面（Kimi）"""
    DEFAULT_API_BASE = "https://api.moonshot.cn/v1"
    DEFAULT_MODEL = "moonshot-v1-8k"

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model)
        self.api_base = self.DEFAULT_API_BASE


class StepfunLLM(OpenAICompatibleLLM):
    """Stepfun / 阶跃星辰"""
    DEFAULT_API_BASE = "https://api.stepfun.com/v1"
    DEFAULT_MODEL = "step-2-16k-nightly"

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model)
        self.api_base = self.DEFAULT_API_BASE


class SiliconFlowLLM(OpenAICompatibleLLM):
    """硅基流动（SiliconFlow）—— 提供大量开源模型的 API"""
    DEFAULT_API_BASE = "https://api.siliconflow.cn/v1"
    DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model)
        self.api_base = self.DEFAULT_API_BASE
