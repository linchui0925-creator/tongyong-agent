"""Ollama 本地 LLM 实现

W4-34 改:
1. 切到 OpenAI 兼容端点 /v1/chat/completions (ollama 0.1.14+ 稳定支持),
   继承 OpenAICompatibleLLM, 自动获得 tools 传 + tool_calls 解析 + 重试。
2. 保留 get_embedding / initialize 的特殊点 (ollama 原生 /api 端点, 用 prompt 字段, /tags 探活)。
3. api_key 改为可选 (本地 ollama 不需要 key)。

旧实现走 /api/chat 原生端点, body 不传 tools, 永远只回纯文本 — 已修。
"""
import logging
from typing import List

import httpx

from app.llm.openai_compatible import OpenAICompatibleLLM
from app.core.base import Message
from app.llm.request_contract import ModelRequestOptions

logger = logging.getLogger(__name__)

# ollama 原生 API 根 (用于 embedding + 探活, 不参与 chat)
_OLLAMA_NATIVE_BASE = "http://localhost:11434/api"


class OllamaLLM(OpenAICompatibleLLM):
    DEFAULT_MODEL = "llama3"
    # OpenAI 兼容端点 (ollama 0.1.14+ 支持 function calling)
    DEFAULT_API_BASE = "http://localhost:11434/v1"

    def __init__(self, api_key: str = None, model: str = None):
        super().__init__(api_key, model)

    async def chat(self, messages: List[Message], tools=None, request_options: ModelRequestOptions = None, **kwargs):
        return await super().chat(messages, tools=tools, request_options=request_options, **kwargs)

    async def stream_chat(self, messages: List[Message], request_options: ModelRequestOptions = None):
        async for chunk in super().stream_chat(messages, request_options=request_options):
            yield chunk

    async def get_embedding(self, text: str) -> List[float]:
        # ollama 原生 /api/embeddings 用 prompt 不是 input
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{_OLLAMA_NATIVE_BASE}/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                response.raise_for_status()
                result = response.json()
                if "embedding" in result:
                    return result["embedding"]
        except Exception as e:
            logger.warning(f"ollama embedding 失败, 用 fallback hash: {e}")

        # fallback: hash 派生伪向量
        import hashlib
        hash_bytes = hashlib.sha256(text.encode()).digest()
        return [(hash_bytes[i % len(hash_bytes)] / 128.0) - 1.0 for i in range(1024)]

    async def initialize(self) -> bool:
        # 走 /tags 探活, 不烧一次 chat
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{_OLLAMA_NATIVE_BASE}/tags")
                self._initialized = response.status_code == 200
                return self._initialized
        except Exception:
            self._initialized = False
            return False
