"""Turn-level prompt hints.

This module provides a lightweight bridge between high-level routing decisions
and the assembled prompt context. It intentionally stays small so it can mirror
OpenCode-style mode hints without taking over the full prompt architecture.
"""
from __future__ import annotations

from app.core.context_source import ContextSource


def build_turn_prompt(turn_strategy) -> list[ContextSource]:
    if not turn_strategy:
        return []

    sections = []
    if getattr(turn_strategy, "should_ask", False):
        sections.append(
            ContextSource(
                key="turn_mode_ask",
                order=15,
                render=(
                    "## 当前轮次模式：ask / clarify\n"
                    "当前信息不足，优先提出最关键的问题，避免猜测。\n"
                    "问题要短，围绕下一步是否能继续执行所需的信息。"
                ),
                source_type="dynamic",
                removable=True,
                metadata={"mode": "ask"},
            )
        )
    elif getattr(turn_strategy, "should_plan", False):
        sections.append(
            ContextSource(
                key="turn_mode_plan",
                order=15,
                render=(
                    "## 当前轮次模式：plan / planner\n"
                    "先拆分任务、比较方案、明确步骤，再进入执行。\n"
                    "计划要尽量短，聚焦可执行步骤和关键依赖。"
                ),
                source_type="dynamic",
                removable=True,
                metadata={"mode": "plan"},
            )
        )
    elif getattr(turn_strategy, "should_use_tools", False):
        sections.append(
            ContextSource(
                key="turn_mode_exec",
                order=16,
                render=(
                    "## 当前轮次模式：build / executor\n"
                    "需要真实工具调用来完成任务；禁止空谈完成。\n"
                    "工具失败要如实说明，结果要能回到证据链。"
                ),
                source_type="dynamic",
                removable=True,
                metadata={"mode": "build"},
            )
        )
    if getattr(turn_strategy, "should_summarize", False):
        sections.append(
            ContextSource(
                key="turn_mode_summary",
                order=17,
                render=(
                    "## 当前轮次模式：summary / reporter\n"
                    "优先给出结构化结论、关键发现和下一步建议。\n"
                    "避免冗长铺陈，结论先行。"
                ),
                source_type="dynamic",
                removable=True,
                metadata={"mode": "summary"},
            )
        )
    return sections
