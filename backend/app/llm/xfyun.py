"""讯飞星火 LLM 实现

W4-34 改: 继承 OpenAICompatibleLLM,自动获得 tools 传 + tool_calls 解析 + 重试。
旧实现 chat() 不传 tools 字段,LLM 永远只回纯文本 — 已修。
注: 讯飞 v4.0 端点 (https://spark-api.xf-yun.com/v4.0/chat) 实际是讯飞自家协议
不是标准 OpenAI 协议。如果配的是 v1.1/v2.0 私有鉴权 (password 字段),需要
override chat() 加鉴权头。此处保持 OpenAI 兼容假定 (Bearer 头),如失败可回退。
"""
from app.llm.openai_compatible import OpenAICompatibleLLM


class XfyunLLM(OpenAICompatibleLLM):
    DEFAULT_MODEL = "spark-v4.0"
    DEFAULT_API_BASE = "https://spark-api.xf-yun.com/v4.0/chat"
