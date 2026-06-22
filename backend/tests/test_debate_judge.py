"""
辩论 Judge 回归测试 (W4-8 修复 2026-06-21)

覆盖范围：
- DebateJudgeAction.run 用 msg.metadata["debate_side"] 分类
- 英文角色名 + 显式 metadata 准确分桶
- 兜底: 名字包含"正方/反方"也能正确分类 (兼容老消息)
- debate_side="judge" 不进任何桶
- role._act() 自动把 debate_side/debate_position 写到消息 metadata

历史:
- 之前 DebateJudgeAction 用 `if "正方" in msg.sent_from` 字符串匹配
- 英文名 ("Biden"/"Pro") 全判错 / 全归 negative
- 510bff1 commit 已点名 DebateJudge 修复遗留 → 本测试锁住修复
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.multi_agent.message import TeamMessage, new_message
from app.core.multi_agent.role import RoleContext, TeamRole
from app.core.multi_agent.actions.debate import DebateJudgeAction
from app.core.multi_agent.actions.base import _call_llm


# ── Fixtures ─────────────────────────────────────────

def make_role(name: str, debate_side: str = "", debate_position: str = "") -> TeamRole:
    """构造辩论角色（避免触发 Pydantic 字段验证问题）"""
    role = TeamRole(
        name=name,
        profile=f"Test debater {name}",
        watch_actions=["DebateSpeech", "SpeakAloud"],
        actions=[DebateJudgeAction()],
        action_types=["DebateJudge"],
        debate_side=debate_side,
        debate_position=debate_position,
    )
    return role


def make_speech(sent_from: str, content: str, side: str = "", position: str = "") -> TeamMessage:
    """构造辩手发言消息"""
    metadata = {}
    if side:
        metadata["debate_side"] = side
    if position:
        metadata["debate_position"] = position
    return new_message(
        content=content,
        role="assistant",
        sent_from=sent_from,
        send_to="Judge",
        cause_by="DebateSpeech",
        metadata=metadata or None,
    )


def make_context(news: list) -> RoleContext:
    """构造 RoleContext，注入 news"""
    ctx = RoleContext(round=1)
    ctx.news = news
    return ctx


# ── 1. 英文名 + 显式 metadata ─────────────────────────

@pytest.mark.asyncio
async def test_judge_uses_metadata_side_for_english_names():
    """
    P0-2 修复主目标: 英文角色名 ("Biden"/"Trump") + metadata.debate_side
    应当被准确分到正方/反方桶，而不是全部走 name 匹配漏判。
    """
    role = make_role("JudgeBot", debate_side="judge", debate_position="judge")
    action = DebateJudgeAction()
    news = [
        # 用户辩题
        new_message(content="Should AI be regulated?", role="user",
                    sent_from="user", cause_by="UserRequirement"),
        make_speech("Biden", "AI regulation is necessary", side="positive", position="first"),
        make_speech("Trump", "AI regulation stifles innovation", side="negative", position="first"),
    ]
    ctx = make_context(news)

    # Mock _call_llm 拿 prompt 验证分类正确
    captured = {}
    async def fake_call_llm(*args, **kwargs):
        captured["messages"] = kwargs.get("messages") or args[1]
        return "judgment result"

    with patch("app.core.multi_agent.actions.debate._call_llm", side_effect=fake_call_llm):
        await action.run(role, ctx)

    user_prompt = captured["messages"][0]["content"]
    # 英文名不在原文中（不写回 prompt），所以通过内容区分
    assert "Biden" in user_prompt
    assert "Trump" in user_prompt
    # 关键: Biden 进正方桶, Trump 进反方桶
    assert "正方辩手发言" in user_prompt
    assert "反方辩手发言" in user_prompt
    # 分类必须准确 (W4-8 修复后)
    pos_section = user_prompt.split("## 反方辩手发言")[0]
    neg_section = user_prompt.split("## 反方辩手发言")[1]
    assert "Biden" in pos_section and "Biden: AI regulation is necessary" in pos_section
    assert "Trump" in neg_section and "Trump: AI regulation stifles innovation" in neg_section


# ── 2. 兜底: 名字含"正方/反方" ─────────────────────────

@pytest.mark.asyncio
async def test_judge_falls_back_to_name_match_for_legacy_messages():
    """
    老消息 (无 metadata) 应该走名字匹配兜底。
    中文名 "正方一辩" / "反方一辩" → 正/反方桶
    """
    role = make_role("JudgeBot")
    action = DebateJudgeAction()
    news = [
        new_message(content="辩题: 测试", role="user", sent_from="user", cause_by="UserRequirement"),
        make_speech("正方一辩", "正方一辩发言"),  # 无 metadata
        make_speech("反方一辩", "反方一辩发言"),  # 无 metadata
    ]
    ctx = make_context(news)

    captured = {}
    async def fake_call_llm(*args, **kwargs):
        captured["messages"] = kwargs.get("messages") or args[1]
        return "judgment"

    with patch("app.core.multi_agent.actions.debate._call_llm", side_effect=fake_call_llm):
        await action.run(role, ctx)

    user_prompt = captured["messages"][0]["content"]
    pos_section = user_prompt.split("## 反方辩手发言")[0]
    neg_section = user_prompt.split("## 反方辩手发言")[1]
    assert "正方一辩" in pos_section
    assert "反方一辩" in neg_section


# ── 3. judge 角色不进正反方桶 ─────────────────────────

@pytest.mark.asyncio
async def test_judge_excludes_judge_role_from_both_buckets():
    """
    裁判 (debate_side="judge") 的发言不应该进入正方或反方桶。
    """
    role = make_role("JudgeBot")
    action = DebateJudgeAction()
    news = [
        new_message(content="辩题", role="user", sent_from="user", cause_by="UserRequirement"),
        make_speech("JudgeBot", "我是裁判", side="judge", position="judge"),
        make_speech("正方一辩", "正方发言"),
        make_speech("反方一辩", "反方发言"),
    ]
    ctx = make_context(news)

    captured = {}
    async def fake_call_llm(*args, **kwargs):
        captured["messages"] = kwargs.get("messages") or args[1]
        return "judgment"

    with patch("app.core.multi_agent.actions.debate._call_llm", side_effect=fake_call_llm):
        await action.run(role, ctx)

    user_prompt = captured["messages"][0]["content"]
    pos_section = user_prompt.split("## 反方辩手发言")[0]
    neg_section = user_prompt.split("## 反方辩手发言")[1]
    # judge 不应进任何桶
    assert "JudgeBot" not in pos_section
    assert "JudgeBot" not in neg_section


# ── 4. metadata 显式覆盖名字匹配 ─────────────────────────

@pytest.mark.asyncio
async def test_judge_metadata_overrides_name_match():
    """
    角色名 "正方一辩" (中文), metadata 显式标 side="negative" → 应进反方桶
    验证 metadata 优先级高于名字匹配。
    """
    role = make_role("JudgeBot")
    action = DebateJudgeAction()
    news = [
        new_message(content="辩题", role="user", sent_from="user", cause_by="UserRequirement"),
        # 名字像正方, metadata 标反方 → 应进反方桶
        make_speech("正方一辩", "我是卧底", side="negative", position="first"),
        make_speech("反方一辩", "正常反方发言"),  # 无 metadata → 走名字
    ]
    ctx = make_context(news)

    captured = {}
    async def fake_call_llm(*args, **kwargs):
        captured["messages"] = kwargs.get("messages") or args[1]
        return "judgment"

    with patch("app.core.multi_agent.actions.debate._call_llm", side_effect=fake_call_llm):
        await action.run(role, ctx)

    user_prompt = captured["messages"][0]["content"]
    pos_section = user_prompt.split("## 反方辩手发言")[0]
    neg_section = user_prompt.split("## 反方辩手发言")[1]
    # 关键: "正方一辩" 因 metadata=negative 应进反方
    assert "正方一辩" not in pos_section
    assert "正方一辩" in neg_section
    assert "我是卧底" in neg_section


# ── 5. role._act() 自动写 metadata ─────────────────────────

@pytest.mark.asyncio
async def test_role_act_attaches_debate_side_to_metadata():
    """
    W4-8 修复: role._act() 应当把 role.debate_side / debate_position
    写到产生的消息 metadata, 让下游 DebateJudgeAction 能读到。
    """
    from app.core.multi_agent.actions.base import TeamAction

    class EchoAction(TeamAction):
        name: str = "Echo"
        async def run(self, role, context):
            return "echo content"

    role = make_role("Biden", debate_side="positive", debate_position="first")
    role.actions = [EchoAction()]
    role._rc = RoleContext(round=1, news=[
        new_message(content="test", role="user", sent_from="user", cause_by="UserRequirement")
    ])
    role._rc.todo = EchoAction()

    msg = await role._act()
    assert msg is not None
    assert msg.metadata.get("debate_side") == "positive"
    assert msg.metadata.get("debate_position") == "first"


@pytest.mark.asyncio
async def test_role_act_does_not_attach_debate_metadata_for_non_debate_role():
    """
    非辩论角色 (无 debate_side / debate_position) 不应被强制写入 metadata。
    """
    from app.core.multi_agent.actions.base import TeamAction

    class EchoAction(TeamAction):
        name: str = "Echo"
        async def run(self, role, context):
            return "echo content"

    role = TeamRole(name="Coder", actions=[EchoAction()])
    role._rc = RoleContext(round=1, news=[
        new_message(content="test", role="user", sent_from="user", cause_by="UserRequirement")
    ])
    role._rc.todo = EchoAction()

    msg = await role._act()
    assert msg is not None
    # 不应出现 debate_side/debate_position 字段
    assert "debate_side" not in msg.metadata
    assert "debate_position" not in msg.metadata


# ── 6. SpeakAloud 走同一分类路径 ─────────────────────────

@pytest.mark.asyncio
async def test_judge_handles_speakaloud_with_metadata():
    """
    SpeakAloud 走同一分类逻辑 (cause_by in DebateSpeech/SpeakAloud),
    metadata 显式 side 应被尊重。
    """
    role = make_role("JudgeBot")
    action = DebateJudgeAction()
    news = [
        new_message(content="辩题", role="user", sent_from="user", cause_by="UserRequirement"),
        new_message(
            content="Pro speaks freely", role="assistant",
            sent_from="Pro", send_to="", cause_by="SpeakAloud",
            metadata={"debate_side": "positive"},
        ),
        new_message(
            content="Con speaks freely", role="assistant",
            sent_from="Con", send_to="", cause_by="SpeakAloud",
            metadata={"debate_side": "negative"},
        ),
    ]
    ctx = make_context(news)

    captured = {}
    async def fake_call_llm(*args, **kwargs):
        captured["messages"] = kwargs.get("messages") or args[1]
        return "judgment"

    with patch("app.core.multi_agent.actions.debate._call_llm", side_effect=fake_call_llm):
        await action.run(role, ctx)

    user_prompt = captured["messages"][0]["content"]
    pos_section = user_prompt.split("## 反方辩手发言")[0]
    neg_section = user_prompt.split("## 反方辩手发言")[1]
    assert "Pro" in pos_section
    assert "Con" in neg_section
