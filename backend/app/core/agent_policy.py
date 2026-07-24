"""High-level agent policy primitives.

This module sits above runtime/context plumbing and captures the turn-level
intent and execution strategy in a structured form so the agent can reason
about *what kind* of task it is handling before it decides *how* to execute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class AgentIntent:
    kind: str
    confidence: float
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TurnStrategy:
    mode: str
    should_use_tools: bool
    should_plan: bool
    should_ask: bool
    should_summarize: bool
    sandbox_mode: str = "off"
    sandbox_preset: str = ""
    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentPolicy:
    """Lightweight heuristic policy for routing a turn."""

    TOOL_HINTS: Iterable[str] = (
        "请使用", "调用工具", "读取", "打开", "搜索", "截图", "写入", "分析文件", "terminal", "browser", "playwright",
    )
    PLAN_HINTS: Iterable[str] = (
        "分步骤", "计划", "先规划", "逐步", "方案", "路线", "步骤", "执行清单",
    )
    ASK_HINTS: Iterable[str] = (
        "不确定", "需要你", "请补充", "请确认", "澄清", "问一下", "缺少", "信息不足",
    )
    SUMMARY_HINTS: Iterable[str] = (
        "总结", "归纳", "汇总", "整理", "提炼", "回顾",
    )

    def infer_intent(self, message: str) -> AgentIntent:
        text = (message or "").casefold()
        reasons: List[str] = []
        score = 0.0

        if any(hint in text for hint in self.TOOL_HINTS):
            score += 0.4
            reasons.append("tool_hint")
        if any(hint in text for hint in self.PLAN_HINTS):
            score += 0.25
            reasons.append("plan_hint")
        if any(hint in text for hint in self.ASK_HINTS):
            score += 0.15
            reasons.append("ask_hint")
        if any(hint in text for hint in self.SUMMARY_HINTS):
            score += 0.1
            reasons.append("summary_hint")

        if score >= 0.5:
            kind = "action"
        elif score >= 0.25:
            kind = "mixed"
        else:
            kind = "conversational"

        return AgentIntent(kind=kind, confidence=min(score, 1.0), reasons=reasons)

    def choose_strategy(self, message: str, *, has_attachments: bool = False, is_plan_mode: bool = False) -> TurnStrategy:
        intent = self.infer_intent(message)
        text = (message or "").casefold()

        should_use_tools = intent.kind in {"action", "mixed"} or has_attachments
        should_plan = is_plan_mode or ("计划" in text and should_use_tools)
        should_ask = any(hint in text for hint in self.ASK_HINTS) and not should_use_tools
        should_summarize = intent.kind == "conversational" and any(hint in text for hint in self.SUMMARY_HINTS)
        sandbox_mode = "off"
        sandbox_preset = ""
        if should_use_tools:
            sandbox_mode = "macos"
            sandbox_preset = "workspace_only" if has_attachments or should_plan else "network_off"
        if should_ask:
            should_plan = False
            should_summarize = False
            sandbox_mode = "off"
            sandbox_preset = ""
        if should_plan:
            should_use_tools = True
            should_summarize = False
            sandbox_mode = "macos"
            sandbox_preset = "workspace_only"

        notes = []
        if should_plan:
            notes.append("plan_before_execute")
        if should_use_tools:
            notes.append("tool_ready")
        if should_ask:
            notes.append("ask_for_clarification")
        if has_attachments:
            notes.append("attachment_context")

        return TurnStrategy(
            mode=intent.kind,
            should_use_tools=should_use_tools,
            should_plan=should_plan,
            should_ask=should_ask,
            should_summarize=should_summarize,
            sandbox_mode=sandbox_mode,
            sandbox_preset=sandbox_preset,
            notes=notes,
            metadata={"intent_confidence": intent.confidence, "intent_reasons": intent.reasons},
        )
