"""
LLM LangChain 适配器 — 把 BaseLLM 包装为 LangChain BaseChatModel

让现有的 LLM provider（MiniMax、DeepSeek、OpenAI 等）可以直接用于 LangChain Agent。
"""

import logging
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)

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

    # ── 流式生成 (W4-2 修复 2026-06-09) ─────────────────────
    # 根因：之前没实现 _astream/_stream, langchain astream_events 走 on_chat_model_end
    #   一次性推完整 AIMessage, 前端 SSE 只收 1 个 chunk, 不是真"打字机"。
    # 修法：实现 _astream, 调 base_llm.stream_chat (已存在的 async generator),
    #   每个 delta 包装成 AIMessageChunk + ChatGenerationChunk yield 出去。
    #   LangChain 会自动累积 chunk, 在 on_chat_model_end 推合并后的 AIMessage,
    #   里面带 usage_metadata (从 llm_output["token_usage"] 拿)。

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """异步流式生成 — 真正按 token 流到前端

        W4-47 修 (CRITICAL): 旧版只走 stream_chat() yield content, **丢掉 tool_calls**.
        后果: reasoning model (deepseek-v4-flash / GLM-5.2) 把工具调用放 reasoning_content,
        XML 解析后 LLMResponse.tool_calls 非空, 但 _astream 不传 tool_calls 给 chunk,
        LangChain 累积 chunk 时丢 tool_calls → 整轮 agent 0 tool call → "任务中断".

        修法: 改走 chat() 拿完整 LLMResponse (含 content + tool_calls), 然后:
        1. yield content 字符 (逐字, 模拟流式)
        2. 最后 yield 一个 chunk 带 tool_calls (langchain AIMessageChunk.__add__ 累积)
        3. reasoning / thinking 走 _base_llm.chat() 已经提取到 LLMResponse.thinking
        """
        internal_messages = _lc_to_internal(messages)
        full_text_parts: List[str] = []
        tool_calls_data: List[Dict] = []

        # 1. 调 chat() 拿完整响应 (含 content + tool_calls + thinking + usage)
        #    _agenerate_with_cache 仍会先尝试 stream, 走这条路才能拿到 tool_calls
        try:
            llm_response: LLMResponse = await self._base_llm.chat(
                messages=internal_messages,
                tools=self._tools_schema,
            )
        except Exception as e:
            logger.warning(f"[W4-47] _astream chat() 失败, 降级: {e}")
            # 降级: 走 _agenerate
            result = await self._agenerate(messages, stop, run_manager, **kwargs)
            ai_msg = result.generations[0].message
            yield ChatGenerationChunk(message=AIMessageChunk(
                content=ai_msg.content,
                tool_calls=ai_msg.tool_calls,
            ))
            return

        # W5-5 修 (2026-07-15): 推理型模型 (GLM-4.5V 等) 真实体验:
        #   `chat()` 拿到的 LLMResponse.thinking 里是完整 reasoning_content 分片,
        #   但 _astream 之前完全忽略, 导致前端"思考阶段"看不到任何字, 一直"正在思考..."。
        #   修法: 先把 thinking 用 <think>...</think> 包起来逐字 yield,
        #   下游 langchain_agent.on_chat_model_stream 会切成 thinking_delta 事件,
        #   前端折叠成"💭 思考过程"面板; 再 yield content 作为正式答案。
        thinking_text = "".join(llm_response.thinking or []).strip()
        if thinking_text:
            # 逐 chunk yield: "<think>" 整段 → 思考正文逐字 → "</think>" 整段。
            # 不逐字拆 "<think>" (否则 on_chat_model_stream 里 THINK_OPEN.search 每次
            # 只看到 1 字符, 匹配不到, 会当成 content 吐给前端)。
            for tok in ("<think>", thinking_text, "</think>"):
                chunk_msg = AIMessageChunk(content=tok)
                chunk = ChatGenerationChunk(message=chunk_msg)
                if run_manager:
                    await run_manager.on_llm_new_token(tok, chunk=chunk)
                yield chunk

        # 2. yield content 字符 (流式体验)
        if llm_response.content:
            for ch in llm_response.content:
                full_text_parts.append(ch)
                chunk_msg = AIMessageChunk(content=ch)
                chunk = ChatGenerationChunk(message=chunk_msg)
                if run_manager:
                    await run_manager.on_llm_new_token(ch, chunk=chunk)
                yield chunk
        elif llm_response.has_tool_calls:
            # 兜底: reasoning model 可能 content="" 全部在 reasoning_content,
            # 必须 yield 至少 1 个 chunk 让 langchain 不抛 "No generations found in stream"
            # 内容是空的, 但 tool_calls 必须传播
            pass

        # 3. yield final chunk 带 tool_calls (langchain 通过 AIMessageChunk.__add__ 累积)
        if llm_response.has_tool_calls:
            for tc in llm_response.tool_calls:
                tool_calls_data.append({
                    "name": tc.tool_name,
                    "args": tc.arguments,
                    "id": tc.tool_call_id or f"call_{tc.tool_name}",
                    "type": "tool_call",
                })
            final_chunk = ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_calls=tool_calls_data,
            ))
            yield final_chunk

        # 4. usage 走 response_metadata (on_chat_model_end 时 langchain 读)
        #    实际处理在 _agenerate 的 llm_output 路径, 这里只是占位

        # 注意：完整 usage 在 _agenerate 的 llm_output 里有, 但 _astream 不返回 ChatResult。
        # usage 走两条路兜底:
        #   1) on_chat_model_end 事件读 message_metadata (chunks 累积)
        #   2) 最后一次 yield 一个特殊 chunk 带 usage_metadata
        # 简化做法: astream_events v2 在 on_chat_model_end 时, LangChain 内部
        #   会读 llm_output 字段 — 但 _astream 不返回 ChatResult...
        # 兜底: 触发一个 chat 拿 usage 是不优的, 我们让 langchain_agent 收尾时
        #   单独统计 tokens (按字符数估算, 注释清楚精度)。

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """同步流式 — 走 _astream 包装"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                async def collect():
                    out = []
                    async for c in self._astream(messages, stop, None, **kwargs):
                        out.append(c)
                    return out
                chunks = pool.submit(asyncio.run, collect()).result(timeout=120)
                for c in chunks:
                    yield c
        else:
            async def collect():
                out = []
                async for c in self._astream(messages, stop, None, **kwargs):
                    out.append(c)
                return out
            for c in asyncio.run(collect()):
                yield c

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model": self._base_llm.model,
            "model_name": self._base_llm.model,  # W4-2: 兼容 LangChain 新版
            "provider": self._base_llm.__class__.__name__,
        }
