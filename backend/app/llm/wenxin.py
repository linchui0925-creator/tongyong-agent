"""百度文心 LLM 实现 (qianfan v2 OpenAI 兼容)

W4-34 改: 继承 OpenAICompatibleLLM,自动获得 tools 传 + tool_calls 解析 + 重试。
旧实现 chat() 不传 tools 字段,LLM 永远只回纯文本 — 已修。
"""
from app.llm.openai_compatible import OpenAICompatibleLLM


class WenxinLLM(OpenAICompatibleLLM):
    DEFAULT_MODEL = "ernie-4.0-8k-latest"
    DEFAULT_API_BASE = "https://qianfan.baidubce.com/v2/chat/completions"
