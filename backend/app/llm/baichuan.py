"""百川智能 LLM 实现

W4-34 改: 继承 OpenAICompatibleLLM,自动获得 tools 传 + tool_calls 解析 + 重试。
旧实现 chat() 不传 tools 字段,LLM 永远只回纯文本 — 已修。
"""
from app.llm.openai_compatible import OpenAICompatibleLLM


class BaichuanLLM(OpenAICompatibleLLM):
    DEFAULT_MODEL = "Baichuan4"
    DEFAULT_API_BASE = "https://api.baichuan-ai.com/v1"
