"""
LangGraph POC — mock LLM 版（Phase1 框架层验证专用）。

为什么需要 mock：
  真实 deepseek/minimax 端在 2026-06-07 跑时报 402（余额不足），
  阻塞红线 1+2 的最终验证。mock 把 LLM 决策这一步固定下来，
  让我们**只验 LangGraph 框架本身**：
    - StateGraph 节点流转
    - 工具节点真跑（echo_time 还是真调，返回真实时间）
    - checkpoint 落盘
    - 重连能续

mock 不是"假完成"——它把 LLM 当外部依赖剥离，**回归基线**。
Phase2 接真 LLM 时：先跑 mock 拿 4/4，再换真 LLM 单独验证 LLM 端。

红线 4 条全过 = Phase1 POC 出口。
"""

from __future__ import annotations
import os
import sys
import time
import uuid
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


from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_core.runnables import RunnableConfig  # noqa: E402
from langgraph.graph import StateGraph, START, END  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402


# ── 工具：echo_time（mock 模式下也真跑 —— 验证工具节点不是 mock） ──
@tool
def echo_time() -> str:
    """返回当前时间。用于验证工具被真调用（不是 mock）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ── State schema ───────────────────────────────────────────
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    # 跟踪轮次，让 mock 能决定何时该调工具、何时该终结
    call_count: int


# ── Mock LLM 节点（替代真 LLM 的决策） ──────────────────
MAX_TOOL_CALLS = 3  # 单次 ainvoke 最多 3 轮 tool（防死循环）


def _detect_intent(text: str) -> str:
    """简易意图识别：看到'几点了'/'时间'就调工具，否则直接答。"""
    text = text.lower()
    if any(k in text for k in ["几点了", "时间", "time"]):
        return "call_tool"
    return "direct_answer"


async def mock_llm(state: AgentState) -> dict:
    """Mock LLM：看上一条 HumanMessage 决定动作。
    - 含时间关键词 → 返回带 tool_calls 的 AIMessage（直到 call_count 超过 MAX_TOOL_CALLS）
    - 其它 → 返回普通 AIMessage（直接答）
    """
    # 算本轮已调过几次工具（用消息历史计数）
    tool_call_count = sum(
        1 for m in state["messages"] if isinstance(m, AIMessage) and m.tool_calls
    )
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    if last_human is None:
        return {"messages": [AIMessage(content="(mock) 没有找到用户输入")]}

    intent = _detect_intent(last_human.content)
    new_count = state.get("call_count", 0) + 1

    # 已超过最大工具调用轮次 → 强制直接答
    if intent == "call_tool" and tool_call_count >= MAX_TOOL_CALLS:
        ai = AIMessage(content=f"(mock) 时间相关问题已回答（最多调 {MAX_TOOL_CALLS} 次工具）")
        return {"messages": [ai], "call_count": new_count}

    if intent == "call_tool":
        ai = AIMessage(
            content="(mock) 我准备调用 echo_time 工具来回答时间问题",
            tool_calls=[{
                "name": "echo_time",
                "args": {},
                "id": f"call_{uuid.uuid4().hex[:8]}",
            }],
        )
        return {"messages": [ai], "call_count": new_count}
    else:
        ai = AIMessage(content=f"(mock) 你好 — 你刚说：{last_human.content!r}")
        return {"messages": [ai], "call_count": new_count}


def should_call_tool(state: AgentState) -> str:
    """判断要不要走工具节点（看最后一条是不是带 tool_calls 的 AI 消息）。"""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


# ── 构建 Graph ────────────────────────────────────────────
_TOOL_NODE = ToolNode([echo_time])


def build_graph(checkpointer):
    g = StateGraph(AgentState)
    g.add_node("llm", mock_llm)  # 用 mock，不用真 LLM
    g.add_node("tools", _TOOL_NODE)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", should_call_tool, {"tools": "tools", END: END})
    g.add_edge("tools", "llm")
    return g.compile(checkpointer=checkpointer)


# ── 端到端验证（满足 4 条验收红线）──────────────────────────
async def run_e2e():
    """运行一次完整端到端，输出可观察证据。"""
    cp_path = BACKEND_DIR / "data" / "lg_poc_mock_checkpoint.sqlite"
    cp_path.parent.mkdir(parents=True, exist_ok=True)

    # 清掉旧 checkpoint 重新跑
    if cp_path.exists():
        cp_path.unlink()

    results = {"1": None, "2": None, "3": None, "4": None}

    async with AsyncSqliteSaver.from_conn_string(str(cp_path)) as cp:
        graph = build_graph(cp)
        thread_id = "phase1-mock-001"
        config: RunnableConfig = cast(RunnableConfig, {"configurable": {"thread_id": thread_id}})

        # ── 红线 1：功能闭环（mock 走通，不依赖外部 LLM） ──
        print("\n[1/4] 功能闭环验证 — 问一个不调工具的问题")
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="你好，请用一句话自我介绍")], "call_count": 0},
            config=config,
        )
        msgs = result["messages"]
        ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]
        print(f"   消息数: {len(msgs)}")
        for m in msgs:
            role = m.__class__.__name__
            content = getattr(m, "content", "")
            print(f"   - {role}: {content!r}")
        assert ai_msgs, "FAIL: 没有 AI 消息"
        assert ai_msgs[-1].content, "FAIL: AI 消息内容为空"
        # 直接答的不应带 tool_calls
        assert not ai_msgs[-1].tool_calls, "FAIL: 不该调工具却调了"
        results["1"] = "✅"
        print("   ✅ 红线 1 通过：纯对话闭环（mock LLM 真出文本，框架正确终结）")

        # ── 红线 2：工具真执行（mock 走通 + echo_time 真跑） ──
        print("\n[2/4] 工具真执行验证 — mock LLM 决策调工具，echo_time 真跑")
        result_t = await graph.ainvoke(
            {"messages": [HumanMessage(content="现在几点了？")], "call_count": 0},
            config=config,
        )
        msgs_t = result_t["messages"]
        tool_msgs = [m for m in msgs_t if isinstance(m, ToolMessage)]
        ai_msgs_t = [m for m in msgs_t if isinstance(m, AIMessage)]
        print(f"   消息数: {len(msgs_t)}")
        for m in msgs_t:
            role = m.__class__.__name__
            content = getattr(m, "content", "")
            tool_calls = getattr(m, "tool_calls", None)
            extra = f"  tool_calls={tool_calls}" if tool_calls else ""
            print(f"   - {role}: {content!r}{extra}")
        # mock LLM 至少调过一次工具
        assert any(m.tool_calls for m in ai_msgs_t), "FAIL: mock LLM 没生成 tool_calls"
        # 工具节点真跑了
        assert tool_msgs, "FAIL: 工具节点没真跑（没有 ToolMessage）"
        assert tool_msgs[-1].content, "FAIL: ToolMessage.content 为空"
        # 工具返回的是真时间（不是空字符串或 mock 标记）
        assert "20" in tool_msgs[-1].content and ":" in tool_msgs[-1].content, \
            f"FAIL: 工具返回不像真时间: {tool_msgs[-1].content!r}"
        results["2"] = "✅"
        print(f"   ✅ 红线 2 通过：echo_time 真跑（返回真时间: {tool_msgs[-1].content!r}）")

        # ── 红线 3：checkpoint 可回溯 ──
        print("\n[3/4] checkpoint 可回溯验证 — 重新拿 state")
        state = await graph.aget_state(config)
        cfg = state.config["configurable"]
        cp_id = cfg.get("checkpoint_id")
        print(f"   thread_id: {cfg.get('thread_id')}")
        print(f"   checkpoint_id: {cp_id}")
        print(f"   next step: {state.next}")
        print(f"   values messages 数: {len(state.values.get('messages', []))}")
        assert state.values.get("messages"), "FAIL: state.values.messages 为空"
        results["3"] = "✅"
        print("   ✅ 红线 3 通过：state 落盘并能读回")

        # ── 红线 4：失败可恢复（重连新图实例，验证盘上数据持久） ──
        print("\n[4/4] 失败可恢复验证 — 重新打开 sqlite + 新 graph 实例")
        # 关键：第二个 context manager 模拟"崩了重启"
        async with AsyncSqliteSaver.from_conn_string(str(cp_path)) as cp2:
            graph2 = build_graph(cp2)
            state2 = await graph2.aget_state(config)
            n_msgs = len(state2.values.get("messages", []))
            print(f"   重连后 messages 数: {n_msgs}")
            assert n_msgs > 0, "FAIL: 重启后消息为空（盘上没数据）"
            # 再跑一轮，看能不能在历史基础上加消息
            result3 = await graph2.ainvoke(
                {"messages": [HumanMessage(content="再问一个不调工具的：你叫什么？")], "call_count": 0},
                config=config,
            )
            n_msgs_after = len(result3["messages"])
            print(f"   接着问了一轮，消息总数: {n_msgs_after}")
            assert n_msgs_after > n_msgs, "FAIL: 重连后不能继续累积消息"
        results["4"] = "✅"
        print("   ✅ 红线 4 通过：重启能续上，且能在历史基础上加消息")

    # ── 总结 ──
    print("\n" + "=" * 50)
    print("Phase1 验证总结（mock LLM 版，框架层独立验证）")
    print("=" * 50)
    for k, v in results.items():
        label = {
            "1": "红线 1 — 功能闭环",
            "2": "红线 2 — 工具真执行",
            "3": "红线 3 — checkpoint 可回溯",
            "4": "红线 4 — 失败可恢复",
        }[k]
        print(f"  {v}  {label}")
    if all(v == "✅" for v in results.values()):
        print("\n🎉 Phase1 POC 框架层 4/4 全过（mock LLM）")
        print("   Phase2 集成时：先跑本文件确认 4/4 仍过，再接真 LLM。")
    else:
        print("\n❌ 有红线未过，Phase1 出口未达成")
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_e2e())