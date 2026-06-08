"""
LangGraph POC — 真 LLM 版（Phase2 集成入口）。

前置条件：
  1. backend/.env 里有有效的 DEEPSEEK_API_KEY（或其他 LLM key）
  2. pip install langgraph langchain-core langchain-openai langgraph-checkpoint-sqlite

跑法：
  cd backend && .venv/bin/python3.13 langgraph_poc_real.py

跟 mock 版（langgraph_poc_mock.py）的对照：
  - 同样的 StateGraph 拓扑
  - 同样的 4 条验收红线
  - 唯一区别：call_llm 节点用真 ChatOpenAI 调 deepseek（OpenAI 兼容协议）
  - 跑前请先确认有 LLM 余额（之前 mock 是因为 deepseek 402 才换 mock 的）

红线判定：
  1. 功能闭环：HumanMessage → AI 真回文本（不再是 402）
  2. 工具真执行：LLM 决策调工具 + echo_time 真跑
  3. checkpoint 落盘：aget_state 拿到 checkpoint_id
  4. 重连能续：第二个 AsyncSqliteSaver 上下文拿历史
"""

from __future__ import annotations
import os
import sys
import time
from pathlib import Path
from typing import Annotated, TypedDict, cast

BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

# 手动 source .env（pydantic_settings 在子进程里有时不自动加载）
_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        k, v = _line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


from app.config import Settings  # noqa: E402

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_core.runnables import RunnableConfig  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.graph import StateGraph, START, END  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402


# ── 工具：echo_time ──────────────────────────────────────
@tool
def echo_time() -> str:
    """返回当前时间。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ── State schema ───────────────────────────────────────────
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# ── 真 LLM（OpenAI 兼容协议） ────────────────────────────
def _build_llm() -> ChatOpenAI:
    settings = Settings()
    api_key = settings.deepseek_api_key
    if not api_key:
        raise RuntimeError("deepseek_api_key 未配置 — 检查 .env")
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
        temperature=0,
    )


_llm = _build_llm()
_llm_with_tools = _llm.bind_tools([echo_time])
_TOOL_NODE = ToolNode([echo_time])


async def call_llm(state: AgentState) -> dict:
    """真 LLM 节点：拿 messages → 调 LLM → 返回新消息。"""
    response = await _llm_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}


def should_call_tool(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


# ── 构建 Graph ────────────────────────────────────────────
def build_graph(checkpointer):
    g = StateGraph(AgentState)
    g.add_node("llm", call_llm)
    g.add_node("tools", _TOOL_NODE)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", should_call_tool, {"tools": "tools", END: END})
    g.add_edge("tools", "llm")
    return g.compile(checkpointer=checkpointer)


# ── 端到端验证（满足 4 条验收红线）──────────────────────────
async def run_e2e():
    cp_path = BACKEND_DIR / "data" / "lg_poc_real_checkpoint.sqlite"
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    if cp_path.exists():
        cp_path.unlink()

    results = {"1": None, "2": None, "3": None, "4": None}

    async with AsyncSqliteSaver.from_conn_string(str(cp_path)) as cp:
        graph = build_graph(cp)
        thread_id = "phase1-real-001"
        config: RunnableConfig = cast(RunnableConfig, {"configurable": {"thread_id": thread_id}})

        # ── 红线 1：纯对话（不依赖工具） ──
        print("\n[1/4] 真 LLM 对话：1+1=？")
        try:
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="一句话回答：1+1等于几？只回数字")]},
                config=config,
            )
            msgs = result["messages"]
            ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]
            print(f"   AI 回: {ai_msgs[-1].content!r}")
            assert ai_msgs and ai_msgs[-1].content, "FAIL: AI 没回"
            results["1"] = "✅"
            print("   ✅ 红线 1 通过")
        except Exception as e:
            print(f"   ❌ 红线 1 失败: {type(e).__name__}: {e}")
            results["1"] = f"❌ ({type(e).__name__})"

        # ── 红线 2：工具真执行 ──
        print("\n[2/4] 真 LLM 调工具：请回答当前时间")
        try:
            result_t = await graph.ainvoke(
                {"messages": [HumanMessage(content="现在几点了？必须调用工具来回答")]},
                config=config,
            )
            msgs_t = result_t["messages"]
            tool_msgs = [m for m in msgs_t if isinstance(m, ToolMessage)]
            print(f"   工具调用次数: {len(tool_msgs)}")
            if tool_msgs:
                print(f"   工具返回: {tool_msgs[-1].content!r}")
            if tool_msgs and "20" in tool_msgs[-1].content and ":" in tool_msgs[-1].content:
                results["2"] = "✅"
                print("   ✅ 红线 2 通过")
            else:
                results["2"] = "⚠️ (LLM 没调工具)"
                print("   ⚠️ 红线 2 未完整通过：LLM 没调工具")
        except Exception as e:
            print(f"   ❌ 红线 2 失败: {type(e).__name__}: {e}")
            results["2"] = f"❌ ({type(e).__name__})"

        # ── 红线 3：checkpoint 可回溯 ──
        print("\n[3/4] checkpoint 可回溯")
        try:
            state = await graph.aget_state(config)
            cfg = state.config["configurable"]
            print(f"   checkpoint_id: {cfg.get('checkpoint_id')}")
            print(f"   messages 数: {len(state.values.get('messages', []))}")
            assert state.values.get("messages"), "FAIL: state 空"
            results["3"] = "✅"
            print("   ✅ 红线 3 通过")
        except Exception as e:
            print(f"   ❌ 红线 3 失败: {type(e).__name__}: {e}")
            results["3"] = f"❌ ({type(e).__name__})"

        # ── 红线 4：重连能续 ──
        print("\n[4/4] 重连能续")
        try:
            async with AsyncSqliteSaver.from_conn_string(str(cp_path)) as cp2:
                graph2 = build_graph(cp2)
                state2 = await graph2.aget_state(config)
                n = len(state2.values.get("messages", []))
                print(f"   重连后 messages 数: {n}")
                assert n > 0
                # 再问一句
                r3 = await graph2.ainvoke(
                    {"messages": [HumanMessage(content="再回个简单的'好的'就行")]},
                    config=config,
                )
                n3 = len(r3["messages"])
                print(f"   再问一轮后 messages 数: {n3}")
                assert n3 > n
            results["4"] = "✅"
            print("   ✅ 红线 4 通过")
        except Exception as e:
            print(f"   ❌ 红线 4 失败: {type(e).__name__}: {e}")
            results["4"] = f"❌ ({type(e).__name__})"

    print("\n" + "=" * 50)
    print("Phase1 验证总结（真 LLM 版）")
    print("=" * 50)
    for k, v in results.items():
        label = {
            "1": "红线 1 — 功能闭环",
            "2": "红线 2 — 工具真执行",
            "3": "红线 3 — checkpoint 可回溯",
            "4": "红线 4 — 失败可恢复",
        }[k]
        print(f"  {v}  {label}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_e2e())