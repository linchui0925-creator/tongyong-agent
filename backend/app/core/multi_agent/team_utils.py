"""Multi-agent team helper utilities.

This module keeps pure, easily testable logic out of `team.py`.
The goal is to keep orchestration code focused on control flow while
small deterministic helpers live here.
"""

from __future__ import annotations

import re
from typing import List

from app.core.multi_agent.role import TeamRole

# 辩论模式的默认辩位顺序：先发言者排前，裁判永远在最后。
_DEBATE_POSITION_ORDER = {
    "first": 0,
    "second": 1,
    "third": 2,
    "fourth": 3,
    "judge": 4,
}


def sort_roles_by_debate_position(roles: List[TeamRole]) -> List[TeamRole]:
    """Return roles in debate order.

    Roles without an explicit debate position are placed after judge so the
    visible debate flow remains stable even when the UI inserts roles out of
    order.
    """
    return sorted(roles, key=lambda role: _DEBATE_POSITION_ORDER.get(role.debate_position, 99))


def decompose_idea(idea: str) -> List[str]:
    """Split a high-level idea into smaller task-sized chunks.

    The splitter intentionally stays simple and deterministic:
    - split on common sentence delimiters
    - drop tiny noise fragments
    - always return at least one task

    The helper can later be swapped for an LLM-based decomposer without
    changing the `Team` public API.
    """
    if not idea or not idea.strip():
        return ["(empty)"]

    parts = re.split(r"[.。;；?？！!\n]+", idea)
    parts = [part.strip() for part in parts if part.strip() and len(part.strip()) >= 3]
    return parts if parts else [idea.strip()]
