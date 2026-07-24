"""百川智能 LLM 实现

W4-34 改: 继承 OpenAICompatibleLLM,自动获得 tools 传 + tool_calls 解析 + 重试。
旧实现 chat() 不传 tools 字段,LLM 永远只回纯文本 — 已修。
"""
from app.llm.openai_compatible import OpenAICompatibleLLM
from app.llm.request_contract import ModelRequestOptions


class BaichuanLLM(OpenAICompatibleLLM):
    DEFAULT_MODEL = "Baichuan4"
    DEFAULT_API_BASE = "https://api.baichuan-ai.com/v1"

    async def chat(self, messages, tools=None, request_options: ModelRequestOptions = None, **kwargs):
        return await super().chat(messages, tools=tools, request_options=request_options, **kwargs)

    async def stream_chat(self, messages, request_options: ModelRequestOptions = None):
        async for chunk in super().stream_chat(messages, request_options=request_options):
            yield chunk
