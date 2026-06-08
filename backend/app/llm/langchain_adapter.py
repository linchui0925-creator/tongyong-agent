"""
LLM LangChain 适配器 — 把 BaseLLM 包装为 LangChain BaseChatModel

让现有的 LLM provider（MiniMax、DeepSeek、OpenAI 等）可以直接用于 LangChain Agent。
"""

import logging
from typing import Any, Dict, List, Optional, Iterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.callbacks import CallbackManagerForLLMRun

from app.llm.base import BaseLLM, LLMResponse
from app.core.base import Message

logger = logging.getLogger(__name__)


def _lc_to_internal(messages: List[BaseMessage]) -> List[Message]:
    """LangChain messages → 内部 Message 格式"""
    result = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append(Message(role="system", content=msg.content))
        elif isinstance(msg, HumanMessage):
            result.append(Message(role="user", content=msg.content))
        elif isinstance(msg, AIMessage):
            # AIMessage 可能有 tool_calls，需要序列化为 JSON
            if msg.tool_calls:
                import json
                tool_calls_data = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"], ensure_ascii=False),
                        },
                    }
                    for tc in msg.tool_calls
                ]
                content = json.dumps(
                    {"content": msg.content or "", "tool_calls": tool_calls_data},
                    ensure_ascii=False,
                )
                result.append(Message(role="assistant", content=content))
            else:
                result.append(Message(role="assistant", content=msg.content or ""))
        elif isinstance(msg, ToolMessage):
            # ToolMessage → role="tool" 消息
            import json
            content = json.dumps(
                {"tool_call_id": msg.tool_call_id, "content": msg.content},
                ensure_ascii=False,
            )
            result.append(Message(role="tool", content=content))
        else:
            # 其他类型当作 user 消息
            result.append(Message(role="user", content=msg.content))
    return result


def _internal_to_lc(response: LLMResponse) -> AIMessage:
    """LLMResponse → LangChain AIMessage"""
    tool_calls = []
    if response.has_tool_calls:
        for tc in response.tool_calls:
            tool_calls.append({
                "name": tc.tool_name,
                "args": tc.arguments,
                "id": tc.tool_call_id or f"call_{tc.tool_name}",
                "type": "tool_call",
            })

    return AIMessage(
        content=response.content or "",
        tool_calls=tool_calls,
        additional_kwargs={},
        response_metadata={"usage": response.usage} if response.usage else {},
    )


class TongYongLLMAdapter(BaseChatModel):
    """把 BaseLLM 适配为 LangChain BaseChatModel"""

    _base_llm: Any = None
    _tools_schema: Optional[List[Dict]] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, base_llm: BaseLLM, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "_base_llm", base_llm)

    @property
    def _llm_type(self) -> str:
        return f"tongyong-{self._base_llm.__class__.__name__}"

    def bind_tools(self, tools: List[Any], **kwargs) -> "TongYongLLMAdapter":
        """绑定工具 schema（LangChain Agent 调用）"""
        # 从 StructuredTool 提取 OpenAI function-calling schema
        schemas = []
        for tool in tools:
            if hasattr(tool, "args_schema") and tool.args_schema:
                schema = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.args_schema.model_json_schema()
                        if hasattr(tool.args_schema, "model_json_schema")
                        else {},
                    },
                }
                schemas.append(schema)
        # 创建一个副本，绑定 schema
        adapter = TongYongLLMAdapter(self._base_llm)
        object.__setattr__(adapter, "_tools_schema", schemas)
        return adapter

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """同步生成（通过 asyncio 运行异步方法）"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已在事件循环中，用 nest_asyncio 或直接调用
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self._agenerate(messages, stop, run_manager, **kwargs),
                )
                return future.result(timeout=120)
        else:
            return asyncio.run(
                self._agenerate(messages, stop, run_manager, **kwargs)
            )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步生成"""
        internal_messages = _lc_to_internal(messages)

        # 调用现有 LLM
        response: LLMResponse = await self._base_llm.chat(
            messages=internal_messages,
            tools=self._tools_schema,
        )

        # 转换为 LangChain 格式
        ai_message = _internal_to_lc(response)

        generation = ChatGeneration(message=ai_message)
        return ChatResult(
            generations=[generation],
            llm_output={
                "token_usage": response.usage or {},
                "model_name": self._base_llm.model,
            },
        )

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model": self._base_llm.model,
            "provider": self._base_llm.__class__.__name__,
        }
