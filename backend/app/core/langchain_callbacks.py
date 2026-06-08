"""
LangChain → SSE 事件转换回调

把 LangChain Agent 的执行事件转换为前端期望的 SSE 格式：
- progress: 进度更新
- tool_start: 工具开始执行
- tool_complete: 工具执行完成
- content: 文本内容
- thinking_delta/thinking_done: 思考过程
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Union

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import LLMResult, ChatGenerationChunk
from langchain_core.agents import AgentAction, AgentFinish

from app.tools.registry import registry

logger = logging.getLogger(__name__)


def _get_emoji(tool_name: str) -> str:
    """获取工具 emoji"""
    entry = registry.get_entry(tool_name)
    return entry.emoji if entry else "🔧"


class SSEStreamCallback(AsyncCallbackHandler):
    """把 LangChain Agent 事件转为 SSE 事件"""

    def __init__(self, yield_fn):
        """
        Args:
            yield_fn: async callable，接收 dict 事件并推送到 SSE
        """
        self._yield = yield_fn
        self._tool_start_times: Dict[str, float] = {}

    # ── LLM 事件 ─────────────────────────────────────────

    async def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        await self._yield({"type": "progress", "content": "🤔 等待模型响应...", "timestamp": time.time()})

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        # 不推送，内容通过 on_chat_model_stream 逐 token 推送
        pass

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        await self._yield({"type": "error", "error": str(error), "timestamp": time.time()})

    # ── 流式 token 事件 ─────────────────────────────────

    async def on_chat_model_start(self, serialized: Dict[str, Any], messages: List[List[Any]], **kwargs: Any) -> None:
        """LLM 开始生成（流式模式）"""
        pass

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """逐 token 推送（文本内容）"""
        if token:
            await self._yield({"type": "content", "content": token, "timestamp": time.time()})

    # ── Tool 事件 ─────────────────────────────────────────

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> None:
        tool_name = serialized.get("name", "unknown")
        emoji = _get_emoji(tool_name)
        self._tool_start_times[tool_name] = time.time()

        # 尝试解析输入参数
        try:
            args = json.loads(input_str) if isinstance(input_str, str) else input_str
        except (json.JSONDecodeError, TypeError):
            args = {"input": input_str}

        await self._yield({
            "type": "tool_start",
            "tool_name": tool_name,
            "arguments": args,
            "emoji": emoji,
            "timestamp": time.time(),
        })

    async def on_tool_end(self, output: str, **kwargs: Any) -> None:
        # 从 kwargs 获取工具名
        tool_name = kwargs.get("name", "unknown")
        emoji = _get_emoji(tool_name)
        elapsed = time.time() - self._tool_start_times.pop(tool_name, time.time())

        # 截断预览
        preview = output.strip()[:120].replace("\n", " ") if output else ""
        if len(output.strip()) > 120:
            preview += "..."

        is_error = output.startswith("工具执行失败") if output else False

        await self._yield({
            "type": "tool_complete",
            "tool_name": tool_name,
            "result_preview": preview,
            "duration": round(elapsed, 2),
            "error": is_error,
            "emoji": emoji,
            "timestamp": time.time(),
        })

    async def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        tool_name = kwargs.get("name", "unknown")
        emoji = _get_emoji(tool_name)
        await self._yield({
            "type": "tool_error",
            "tool_name": tool_name,
            "error": str(error),
            "emoji": emoji,
            "timestamp": time.time(),
        })

    # ── Agent 事件 ─────────────────────────────────────────

    async def on_agent_action(self, action: AgentAction, **kwargs: Any) -> None:
        """Agent 决定调用工具"""
        # tool_start 已经处理了，这里可以推送思考过程
        if action.log:
            await self._yield({
                "type": "progress",
                "content": f"💭 {action.log.strip()[:100]}",
                "timestamp": time.time(),
            })

    async def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> None:
        """Agent 完成"""
        # 最终输出通过 content 事件推送
        output = finish.return_values.get("output", "")
        if output:
            await self._yield({
                "type": "content",
                "content": output,
                "timestamp": time.time(),
            })

    # ── Chain 事件 ─────────────────────────────────────────

    async def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any) -> None:
        pass

    async def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:
        pass

    async def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        await self._yield({"type": "error", "error": str(error), "timestamp": time.time()})
