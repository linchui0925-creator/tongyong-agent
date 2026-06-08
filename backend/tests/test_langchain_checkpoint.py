"""
W1-3 测试：AsyncSqliteSaver checkpoint + TongYongLLMAdapter 集成

覆盖:
  - test_use_langchain_persistence  — 同 session_id 跑两轮, 第二轮能看到第一轮历史
  - test_tongyong_llm_adapter_text_stream  — Adapter 文本流式
  - test_tongyong_llm_adapter_tool_call_stream  — Adapter 工具调用流式

跑法: pytest tests/test_langchain_checkpoint.py -v -s
注意: 会调真 LLM, 需 backend/.env 凭证
"""
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import pytest
import httpx
from langchain_core.messages import HumanMessage

BACKEND = Path(__file__).parent.parent
for line in (BACKEND / ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ─────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from app.main import app
    return app


@pytest.fixture
def new_session_id():
    """每次跑返新 session_id, 避免污染"""
    return f"w1-3-{uuid.uuid4().hex[:12]}"


async def stream_session(client, session_id, message, use_langchain=True):
    """发 SSE, 返 (events, content)"""
    body = {
        "session_id": session_id,
        "message": message,
        "use_memory": False,
        "use_langchain": use_langchain,
    }
    seen = {}
    content = ""
    first_tool = None
    t0 = time.time()
    async with client.stream("POST", "/api/chat/stream", json=body,
                             timeout=httpx.Timeout(60.0)) as resp:
        assert resp.status_code == 200, f"HTTP {resp.status_code}"
        async for line in resp.aiter_lines():
            if not line or not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            t = ev.get("type", "unknown")
            seen[t] = seen.get(t, 0) + 1
            if t == "content":
                content += ev.get("content", "")
            if t == "tool_start" and first_tool is None:
                first_tool = ev
    return seen, content, first_tool, time.time() - t0


# ─────────────────────────────────────────────────────────
# Test 1: persistence
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_use_langchain_persistence(app, new_session_id):
    """同 session_id 跑两轮, 第二轮能看到第一轮历史 (checkpoint 持久化)"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 第一轮: 报一个 magic number
        msg1 = "记住这个魔法数字 4711. 简单回 '记住' 两个汉字."
        seen1, content1, _, t1 = await stream_session(
            client, new_session_id, msg1, use_langchain=True)
        print(f"\n[round1] elapsed={t1:.1f}s, content={content1!r}")
        assert "记住" in content1, f"round1 should say 记住: {content1!r}"

        # 第二轮: 问魔法数字
        msg2 = "魔法数字是多少? 只回数字."
        seen2, content2, _, t2 = await stream_session(
            client, new_session_id, msg2, use_langchain=True)
        print(f"[round2] elapsed={t2:.1f}s, content={content2!r}")
        assert "4711" in content2, \
            f"round2 should recall 4711 (checkpoint failed?): {content2!r}"


# ─────────────────────────────────────────────────────────
# Test 2: TongYongLLMAdapter 文本生成 (mock BaseLLM, 不依赖外部 API)
#   ⚠️ TongYongLLMAdapter 真实 _agenerate 调 self._base_llm.chat
#   q1_test 跑通是因为端到端 agent.llm 已配好, 单独调 minimax/tongyi
#   端点错配。集成测用 mock 覆盖接口层就够。
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tongyong_llm_adapter_text_generate():
    """TongYongLLMAdapter._agenerate — 文本响应 (BaseChatModel 子类路径, mock)"""
    from app.llm.langchain_adapter import TongYongLLMAdapter
    from app.llm.base import BaseLLM, LLMResponse

    class MockLLM(BaseLLM):
        async def chat(self, messages, tools=None, **kwargs):
            return LLMResponse(content="这是 mock 响应, 2+2=4")
        async def get_embedding(self, text):
            return [0.0] * 1024
        # ⚠️ provider 不是 BaseLLM 字段, 不需要定义
        async def close(self): pass

    # 设 mock model 走 BaseLLM.__init__ 参数
    adapter = TongYongLLMAdapter(base_llm=MockLLM(model="mock-model"))
    result = await adapter._agenerate(
        [HumanMessage(content="2+2=?")],
        stop=None,
        run_manager=None,
    )
    assert len(result.generations) == 1
    msg = result.generations[0].message
    print(f"\n[adapter _agenerate mock] content={msg.content!r}")
    assert "4" in (msg.content or ""), f"text: {msg.content!r}"
    # 校验 ChatResult.llm_output 路径
    assert result.llm_output and result.llm_output["model_name"] == "mock-model"


# ─────────────────────────────────────────────────────────
# Test 3: TongYongLLMAdapter 工具调用生成 (mock)
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tongyong_llm_adapter_tool_call_generate():
    """TongYongLLMAdapter._agenerate + bind_tools — 工具调用 (mock)"""
    from app.llm.langchain_adapter import TongYongLLMAdapter
    from app.llm.base import BaseLLM, LLMResponse, ToolCallResult
    from app.tools.langchain_adapter import registry_to_langchain_tools

    class MockLLM(BaseLLM):
        async def chat(self, messages, tools=None, **kwargs):
            # 收到 tools schema, 假装调 terminal
            return LLMResponse(
                content="",
                tool_calls=[ToolCallResult(
                    tool_name="terminal",
                    arguments={"command": "date"},
                    tool_call_id="call_mock_1",
                )],
            )
        async def get_embedding(self, text):
            return [0.0] * 1024
        async def close(self): pass

    adapter = TongYongLLMAdapter(base_llm=MockLLM(model="mock-model"))
    tools = registry_to_langchain_tools(tool_names=["terminal"])
    bound = adapter.bind_tools(tools)

    result = await bound._agenerate(
        [HumanMessage(content="查时间")],
        stop=None,
        run_manager=None,
    )
    msg = result.generations[0].message
    tool_calls = getattr(msg, "tool_calls", [])
    print(f"\n[adapter tool_call mock] content={msg.content!r}, tool_calls={len(tool_calls)}")
    assert len(tool_calls) == 1, f"expected 1 tool_call, got {tool_calls!r}"
    assert tool_calls[0]["name"] == "terminal"
    assert tool_calls[0]["args"] == {"command": "date"}
