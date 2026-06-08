"""
LangChain/LangGraph adapter 单元测试 — W1-1 回归基线

覆盖范围:
  - app/llm/langchain_adapter.py  (4 用例)
  - app/tools/langchain_adapter.py (5 用例)

注意: TongYongLLMAdapter 集成测 (BaseChatModel 子类) 放 W1-2 跟 checkpoint 一起做,
这里只测纯函数 + 数据类转换。

⚠️ _lc_to_internal 实际把 tool_calls 序列化进 Message.content (JSON 字符串),
   Message 本身没有 tool_calls 字段 — 这是 langchain_adapter.py:46-50 的现有实现。
   单测验证 content JSON 内的 tool_calls, 不验证字段。

跑法: pytest tests/test_langchain_adapters.py -v
"""
import json
import pytest
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    ToolMessage as LCToolMessage,
    SystemMessage,
)

from app.core.base import Message
from app.llm.base import LLMResponse, ToolCallResult
from app.llm.langchain_adapter import _lc_to_internal, _internal_to_lc
from app.tools.langchain_adapter import (
    _json_type_to_python,
    schema_to_pydantic,
    entry_to_langchain_tool,
    registry_to_langchain_tools,
)
from app.tools.registry import ToolRegistry, ToolEntry


# ─────────────────────────────────────────────────────────
# llm/langchain_adapter.py — 4 用例
# ─────────────────────────────────────────────────────────

class TestLcToInternal:
    """LangChain BaseMessage → tongyong Message 转换"""

    def test_lc_to_internal_human_message(self):
        """简单 user 消息"""
        lc_msgs = [HumanMessage(content="hello")]
        result = _lc_to_internal(lc_msgs)
        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].content == "hello"

    def test_lc_to_internal_assistant_with_tool_calls_in_content(self):
        """AIMessage 带 tool_calls — 实现选择: 序列化进 content (JSON 字符串)"""
        ai = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_1",
                "name": "terminal",
                "args": {"command": "date"},
            }],
        )
        result = _lc_to_internal([ai])
        assert result[0].role == "assistant"
        # content 是 JSON 字符串, 包含 tool_calls 数组
        parsed = json.loads(result[0].content)
        assert "tool_calls" in parsed
        assert len(parsed["tool_calls"]) == 1
        assert parsed["tool_calls"][0]["function"]["name"] == "terminal"
        assert parsed["tool_calls"][0]["function"]["arguments"]
        parsed_args = json.loads(parsed["tool_calls"][0]["function"]["arguments"])
        assert parsed_args == {"command": "date"}

    def test_lc_to_internal_tool_message(self):
        """ToolMessage → role='tool' + content 是 JSON 含 tool_call_id"""
        tm = LCToolMessage(
            content="Sun Jun  7 19:25:44 PDT 2026",
            tool_call_id="call_1",
        )
        result = _lc_to_internal([tm])
        assert result[0].role == "tool"
        parsed = json.loads(result[0].content)
        assert parsed["tool_call_id"] == "call_1"
        assert "Sun Jun  7" in parsed["content"]

    def test_lc_to_internal_mixed_conversation(self):
        """多角色混合: system + user + assistant(tool_call) + tool + assistant"""
        lc_msgs = [
            SystemMessage(content="你是同通用 Agent"),
            HumanMessage(content="几点了"),
            AIMessage(
                content="",
                tool_calls=[{
                    "id": "c1",
                    "name": "terminal",
                    "args": {"command": "date"},
                }],
            ),
            LCToolMessage(content="19:25", tool_call_id="c1"),
            AIMessage(content="现在 19:25"),
        ]
        result = _lc_to_internal(lc_msgs)
        assert len(result) == 5
        assert [m.role for m in result] == ["system", "user", "assistant", "tool", "assistant"]
        # assistant(tool_call) 的 content 应是 JSON
        ai_with_tools = json.loads(result[2].content)
        assert "tool_calls" in ai_with_tools
        # tool 消息的 content 应是 JSON, 含 tool_call_id
        tool_msg = json.loads(result[3].content)
        assert tool_msg["tool_call_id"] == "c1"


class TestInternalToLc:
    """tongyong LLMResponse → LangChain AIMessage 转换"""

    def test_internal_to_lc_text_only(self):
        """纯文本响应 → AIMessage(content=...)"""
        resp = LLMResponse(content="你好", usage={"prompt_tokens": 5, "completion_tokens": 2})
        ai = _internal_to_lc(resp)
        assert isinstance(ai, AIMessage)
        assert ai.content == "你好"
        assert ai.tool_calls == []

    def test_internal_to_lc_with_tool_calls(self):
        """带 tool_calls 的响应 → AIMessage 带 tool_calls 字段"""
        resp = LLMResponse(
            content="",
            tool_calls=[ToolCallResult(
                tool_call_id="call_xyz",
                tool_name="terminal",
                arguments={"command": "ls -la"},
            )],
        )
        ai = _internal_to_lc(resp)
        assert ai.content == ""
        assert len(ai.tool_calls) == 1
        assert ai.tool_calls[0]["id"] == "call_xyz"
        assert ai.tool_calls[0]["name"] == "terminal"
        assert ai.tool_calls[0]["args"] == {"command": "ls -la"}


# ─────────────────────────────────────────────────────────
# tools/langchain_adapter.py — 5 用例
# ─────────────────────────────────────────────────────────

class TestJsonTypeToPython:
    """JSON Schema type → Python type 映射"""

    @pytest.mark.parametrize("json_type,expected", [
        ("string", str),
        ("integer", int),
        ("number", float),
        ("boolean", bool),
        ("array", list),
        ("object", dict),
    ])
    def test_all_supported_types(self, json_type, expected):
        assert _json_type_to_python(json_type) is expected

    def test_unsupported_type_fallback(self):
        """未支持的类型 → str (降级安全)"""
        assert _json_type_to_python("null") is str
        assert _json_type_to_python("unknown") is str


class TestSchemaToPydantic:
    """JSON Schema → Pydantic BaseModel 动态生成"""

    def test_schema_to_pydantic_required_only(self):
        """所有字段 required, 无 default"""
        schema = {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "shell command"},
                "timeout": {"type": "integer", "description": "timeout seconds"},
            },
            "required": ["command"],
        }
        Model = schema_to_pydantic("TerminalArgs", schema)
        m = Model(command="ls")
        assert m.command == "ls"
        assert m.timeout is None
        # 缺必填字段应该报错
        with pytest.raises(Exception):
            Model()

    def test_schema_to_pydantic_with_defaults(self):
        """带 default 值的字段"""
        schema = {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "default": "GET"},
            },
            "required": ["url"],
        }
        Model = schema_to_pydantic("FetchArgs", schema)
        m = Model(url="http://example.com")
        assert m.url == "http://example.com"
        assert m.method == "GET"

    def test_schema_to_pydantic_no_params(self):
        """无参数工具 → 空 BaseModel"""
        schema = {"type": "object", "properties": {}, "required": []}
        Model = schema_to_pydantic("NoArgs", schema)
        m = Model()
        assert m is not None


class TestEntryToLangchainTool:
    """ToolEntry → LangChain StructuredTool 包装"""

    def test_entry_to_langchain_tool_basic(self):
        """基础转换: name + description + func 可调 (async)"""
        async def my_func(command: str) -> str:
            return f"ran: {command}"

        entry = ToolEntry(
            name="my_tool",
            toolset="custom",
            schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            handler=my_func,
            description="do something",
            is_async=True,
        )
        tool = entry_to_langchain_tool(entry)
        assert tool.name == "my_tool"
        assert tool.description == "do something"
        # StructuredTool.ainvoke 异步调用
        import asyncio
        result = asyncio.run(tool.ainvoke({"command": "ls"}))
        assert result == "ran: ls"


class TestRegistryToLangchainTools:
    """ToolRegistry → List[StructuredTool] 批量转换

    ⚠️ registry_to_langchain_tools 的实际签名是 (tool_names: Optional[List[str]]=None)
    不是 (registry: ToolRegistry)。None = 用全局 registry 单例。
    """

    def test_registry_to_langchain_tools_with_explicit_names(self):
        """传 tool_names 列表, 只转换指定工具"""
        from app.tools.langchain_adapter import registry as global_registry

        async def f1(x: str):
            return x
        global_registry.register(
            "tool_a", "custom",
            schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            handler=f1, description="desc a",
        )

        async def f2(y: int):
            return y
        global_registry.register(
            "tool_b", "custom",
            schema={"type": "object", "properties": {"y": {"type": "integer"}}, "required": ["y"]},
            handler=f2, description="desc b",
        )

        tools = registry_to_langchain_tools(tool_names=["tool_a", "tool_b"])
        names = [t.name for t in tools]
        assert "tool_a" in names
        assert "tool_b" in names
        assert len(tools) == 2

    def test_registry_to_langchain_tools_filters(self):
        """check_fn 返回 False 的工具应被过滤 (注意: check_fn() 不传 args)"""
        from app.tools.langchain_adapter import registry as global_registry

        async def f1(x: str):
            return x
        global_registry.register(
            "good", "custom",
            schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            handler=f1, description="good tool",
        )

        async def f2(x: str):
            return x
        global_registry.register(
            "bad", "custom",
            schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            handler=f2, description="bad tool",
            check_fn=lambda: False,  # check_fn() 不传 args
        )

        tools = registry_to_langchain_tools(tool_names=["good", "bad"])
        names = [t.name for t in tools]
        assert "good" in names
        assert "bad" not in names
        assert len(tools) == 1
