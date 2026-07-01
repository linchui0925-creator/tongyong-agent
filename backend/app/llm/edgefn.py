"""EdgeFn.net 代理 provider (智谱 GLM / DeepSeek 等多模型聚合)

W4-41 (2026-06-30): 用户提供 edgefn.net 代理 sk-HJVebvMXb0dEQc2RAe92EeAc2fAc4aF89910D38871016217
- 支持 GLM-5.2 (reasoning model, 原生 function call, 跟 deepseek-v4-flash 类似需要 reasoning_content 兜底)
- 也支持 deepseek 系列 (按 model 字段切)
- 一个 key 多模型, model 由调用方传

测试过的模型 (2026-06-30):
- GLM-5.2: ✅ 200, reasoning_content, 原生 tool_calls
- deepseek-v4-pro: ❌ 403 ModelNotAllowed (key 没权限)
- deepseek-v4-flash: (待测, 之前走 deepseek.com 直连)

API: POST https://api.edgefn.net/v1/chat/completions
Auth: Bearer sk-...
格式: OpenAI 兼容
"""
import logging
from typing import Dict
from app.llm.openai_compatible import OpenAICompatibleLLM
from app.llm.base import LLMResponse

logger = logging.getLogger(__name__)


class EdgeFnLLM(OpenAICompatibleLLM):
    """edgefn.net 通用 provider — 同一 key 走 GLM / DeepSeek 等多模型

    通过 DEFAULT_MODEL 切, 用户调用时传 model 参数覆盖:
        EdgeFnLLM(api_key="sk-...", model="GLM-5.2")
        EdgeFnLLM(api_key="sk-...", model="deepseek-v4-flash")
    """

    DEFAULT_API_BASE = "https://api.edgefn.net/v1"
    DEFAULT_MODEL = "GLM-5.2"  # 智谱 reasoning, 原生 function call

    def __init__(self, api_key: str, model: str = None):
        super().__init__(api_key, model)
        logger.info(f"EdgeFn LLM 初始化完成, model: {self.model}, api_base: {self.api_base}")

    def _parse_response(self, result: Dict) -> LLMResponse:
        """EdgeFn 走 thinking 解析 (跟 DeepSeek 一样是 reasoning model)

        GLM-5.2 实测响应格式:
        - content: "" (空)
        - reasoning_content: "思考过程" (有)
        - tool_calls: [{...}] (原生 function call, 结构化)
        - finish_reason: "tool_calls"
        """
        return self._parse_response_with_thinking(result)
