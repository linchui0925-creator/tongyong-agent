"""
辩论 Action

SpeakAloudAction: 自由辩论发言
DebateSpeechAction: 正规辩论赛发言
DebateJudgeAction: 裁判评判
"""

from pydantic import BaseModel, Field
from typing import TYPE_CHECKING, List, Optional
import logging

from app.core.multi_agent.actions.base import TeamAction, _call_llm

if TYPE_CHECKING:
    from app.core.multi_agent.role import TeamRole, RoleContext

logger = logging.getLogger(__name__)


class SpeakAloudAction(TeamAction):
    """辩论发言 Action（保持纯文本，不涉及 TaskPayload）"""
    name: str = "SpeakAloud"
    description: str = "辩论中对辩题发表意见"

    prompt_template: str = """
## BACKGROUND
Suppose you are {name}, you are in a debate with {opponent_name}. Your character: {profile}
## DEBATE TOPIC
{topic}
## YOUR POSITION
{stance}
## DEBATE HISTORY
Previous rounds:
{context}
## YOUR TURN
Now it's your turn, you should closely respond to your opponent's latest argument,
state your position, defend your arguments, and attack your opponent's arguments.
Craft a strong and emotional response in 80 words, in {name}'s rhetoric and viewpoints.
Stay strictly on the debate topic above and your assigned position.
"""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        topic = ""
        for msg in reversed(context.news):
            if msg.cause_by == "UserRequirement" or msg.role == "user":
                topic = msg.content
                break

        history_lines = []
        seen_ids = set()
        for msg in context.news:
            if msg.id in seen_ids:
                continue
            seen_ids.add(msg.id)
            if msg.sent_from == "Team" or msg.role == "user":
                continue
            if msg.sent_from:
                history_lines.append(f"[{msg.sent_from}]: {msg.content[:200]}")

        mem_text = self.get_memory_text(context)
        if mem_text:
            history_lines.append(f"[你的历史发言]:\n{mem_text}")

        ctx_text = "\n".join(history_lines[-12:]) if history_lines else ""

        stance_text = role.stance if role.stance else f"你的角色是 {role.name}（{role.profile}），请基于角色定位自行决定辩论立场"

        prompt = self.prompt_template.format(
            topic=topic or "请基于上下文自行判断辩题并展开辩论",
            context=ctx_text or "First round, no previous arguments.",
            name=role.name,
            profile=role.profile,
            opponent_name=role.opponent_name,
            stance=stance_text,
        )
        messages = [{"role": "user", "content": prompt}]
        return await _call_llm(role, messages, tools=None)


class DebateSpeechAction(TeamAction):
    """
    正规辩论赛发言 Action。

    辩论赛标准流程：
    1. 正方一辩开场陈词（4分钟）
    2. 反方一辩开场陈词（4分钟）
    3. 正方二辩驳论（3分钟）
    4. 反方二辩驳论（3分钟）
    5. 正方三辩质询（3分钟）
    6. 反方三辩质询（3分钟）
    7. 正方四辩总结陈词（4分钟）
    8. 反方四辩总结陈词（4分钟）
    9. 裁判点评并宣布结果

    本 Action 根据辩手位置（first/second/third/fourth）和阵营（positive/negative）
    生成符合其角色要求的发言。
    """
    name: str = "DebateSpeech"
    description: str = "正规辩论赛发言"

    prompt_template: str = """
## 辩论赛
辩题: {topic}
你的角色: {name}
你的立场: {stance}
你的阵营: {side}
你的辩位: {position}

## 角色职责
{role_duty}

## 辩论历史（近期发言）
{context}

## 发言要求
请按照你的角色和辩位要求，针对辩题发表言论。
- 开场陈词要全面阐述本方观点
- 驳论要针对对方论点进行反驳
- 质询要尖锐，指出对方论证漏洞
- 总结要升华，升华本方立场

请用中文回复，发言内容要符合角色身份，语言犀利有力。
回复长度：100-200字。
"""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        # 提取辩题
        topic = ""
        for msg in reversed(context.news):
            if msg.cause_by == "UserRequirement" or msg.role == "user":
                topic = msg.content
                break

        # 获取辩手位置和阵营。role.py:60 定义 debate_side: str = "" (默认空串),
        #   不能用 getattr fallback (永远拿不到 default)。 用 or-trick: 空串/None 走 name 推断
        position = role.debate_position or "first"
        side = role.debate_side or ("positive" if "正方" in role.name else "negative")
        stance = role.stance or ("正方" if side == "positive" else "反方")

        # 根据辩位确定职责
        role_duties = {
            "first": "开场陈词：全面阐述本方核心观点和论据，为整场辩论定调。",
            "second": "驳论：针对对方一辩的开场陈词进行反驳，补强本方论点。",
            "third": "质询：向对方提问，质询对方论证的漏洞和矛盾之处。",
            "fourth": "总结陈词：回顾本方核心论点，指出对方论证缺陷，升华本方立场。",
            "judge": "裁判职责：综合评判双方表现，宣布胜负。",
        }
        role_duty = role_duties.get(position, "按照角色身份发言")

        # 构建辩论历史
        history_lines = []
        seen_ids = set()
        for msg in context.news:
            if msg.id in seen_ids:
                continue
            seen_ids.add(msg.id)
            if msg.sent_from in ("Team", "user", "") or msg.role == "user":
                continue
            if msg.sent_from and msg.cause_by in ("DebateSpeech", "SpeakAloud"):
                history_lines.append(f"[{msg.sent_from}]: {msg.content[:300]}")

        # 也包含角色自己的历史发言
        mem_text = self.get_memory_text(context)
        if mem_text:
            history_lines.append(f"[你的历史发言]:\n{mem_text[:500]}")

        ctx_text = "\n".join(history_lines[-10:]) if history_lines else "第一轮发言，无历史记录。"

        prompt = self.prompt_template.format(
            topic=topic or "请根据以下内容展开辩论",
            name=role.name,
            stance=stance,
            side="正方" if side == "positive" else "反方",
            position=position,
            role_duty=role_duty,
            context=ctx_text,
        )
        messages = [{"role": "user", "content": prompt}]
        return await _call_llm(role, messages, tools=None)


class DebateJudgeAction(TeamAction):
    """
    裁判评判 Action。
    裁判在双方辩手全部发言完毕后，综合评判并宣布结果。
    """
    name: str = "DebateJudge"
    description: str = "裁判综合评判并宣布辩论结果"

    prompt_template: str = """
## 辩论赛裁判评判

辩题: {topic}

## 正方辩手发言
{positive_speeches}

## 反方辩手发言
{negative_speeches}

## 评判要求
作为裁判，请从以下维度进行评判：
1. 论点深度：双方论据是否充分、论证是否严密
2. 逻辑清晰：论证过程是否有逻辑漏洞
3. 语言表达：语言是否清晰、有说服力
4. 应变能力：反驳是否有力、是否有效应对对方攻击
5. 团队配合：四位辩手是否配合默契

请用中文回复，格式如下：
**胜负判定**: 正方胜 / 反方胜 / 平局
**正方表现**: （简要评价）
**反方表现**: （简要评价）
**最佳辩手**: 正方一辩 / 正方二辩 / 正方三辩 / 正方四辩 / 反方一辩 / 反方二辩 / 反方三辩 / 反方四辩
**裁判点评**: （详细点评双方表现）
"""

    async def run(self, role: "TeamRole", context: "RoleContext") -> str:
        # 提取辩题
        topic = ""
        for msg in reversed(context.news):
            if msg.cause_by == "UserRequirement" or msg.role == "user":
                topic = msg.content
                break

        # 收集正方和反方发言
        positive_speeches = []
        negative_speeches = []
        seen_ids = set()
        for msg in context.news:
            if msg.id in seen_ids:
                continue
            seen_ids.add(msg.id)
            if msg.sent_from in ("Team", "user", "") or msg.role == "user":
                continue
            if msg.cause_by in ("DebateSpeech", "SpeakAloud") and msg.sent_from:
                content = f"{msg.sent_from}: {msg.content[:400]}"
                if "正方" in msg.sent_from:
                    positive_speeches.append(content)
                elif "反方" in msg.sent_from:
                    negative_speeches.append(content)

        pos_text = "\n\n".join(positive_speeches[-8:]) if positive_speeches else "正方暂无发言"
        neg_text = "\n\n".join(negative_speeches[-8:]) if negative_speeches else "反方暂无发言"

        prompt = self.prompt_template.format(
            topic=topic or "辩论赛",
            positive_speeches=pos_text,
            negative_speeches=neg_text,
        )
        messages = [{"role": "user", "content": prompt}]
        return await _call_llm(role, messages, tools=None)
