"""智谱 AI ChatGLM LLM 实现

W4-34 改: 继承 OpenAICompatibleLLM,自动获得 tools 传 + tool_calls 解析 + 重试。
旧实现 chat() 不传 tools 字段,LLM 永远只回纯文本 — 已修。
"""
import logging
from app.llm.openai_compatible import OpenAICompatibleLLM
from app.llm.request_contract import ModelRequestOptions

logger = logging.getLogger(__name__)


class ChatGLMLLM(OpenAICompatibleLLM):
    """智谱 AI ChatGLM LLM 实现类"""

    DEFAULT_MODEL = "glm-4"
    DEFAULT_API_BASE = "https://open.bigmodel.cn/api/paas/v4"

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model)
        logger.info(f"ChatGLM LLM 初始化完成, 模型: {self.model}")
