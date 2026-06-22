"""
辩论 mode round 内执行顺序回归测试 (W4-9 P1-2 修复 2026-06-21)

覆盖范围：
- sort_roles_by_debate_position() 按 debate_position (first/second/third/fourth/judge) 排序
- 兜底: 未填 position 的角色排到 judge 之后
- 输入 list 不被改 (纯函数 / 不副作用)
- 空 list / 单角色不爆
- 多次调用结果稳定

历史:
- team.py:222-243 旧实现直接返回 _roles.values() 插入顺序
- UI 添加角色的顺序可能与 debate_position 顺序不一致
  (e.g. UI 先添加 fourth, 再 first, 再 judge → judge 拿到的发言时间错乱)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.multi_agent.team import sort_roles_by_debate_position
from app.core.multi_agent.role import TeamRole


def make_role(name: str, position: str = "") -> TeamRole:
    """构造辩论角色 (绕开 actions/watch_actions 必填, 只测排序)"""
    return TeamRole(
        name=name,
        profile=f"Test debater {name}",
        watch_actions=[],
        actions=[],
        action_types=[],
        debate_position=position,
    )


# ── 1. 正常排序 ─────────────────────────────────────────

def test_sort_orders_by_debate_position_first_to_judge():
    """
    P1-2 修复主目标: 4 角色 hire 顺序错乱 (fourth→first→judge→second)
    应当被排序为 [first, second, fourth, judge]
    """
    roles = [
        make_role("Four辩", "fourth"),
        make_role("一辩", "first"),
        make_role("Judge", "judge"),
        make_role("二辩", "second"),
    ]
    out = sort_roles_by_debate_position(roles)
    assert [r.name for r in out] == ["一辩", "二辩", "Four辩", "Judge"]


def test_sort_empty_list():
    """空 list 不爆, 返回空 list"""
    assert sort_roles_by_debate_position([]) == []


def test_sort_single_role():
    """单角色原样返回"""
    out = sort_roles_by_debate_position([make_role("一辩", "first")])
    assert [r.name for r in out] == ["一辩"]


# ── 2. 兜底: 未填 / 未知 position 排末尾 ─────────────────────

def test_sort_unknown_position_goes_after_judge():
    """未填 debate_position 的角色应当排在 judge 之后 (兜底 99)"""
    roles = [
        make_role("Judge", "judge"),
        make_role("未填辩位", ""),
        make_role("一辩", "first"),
    ]
    out = sort_roles_by_debate_position(roles)
    assert [r.name for r in out] == ["一辩", "Judge", "未填辩位"]


def test_sort_garbage_position_string_also_goes_after_judge():
    """未知的 position 字符串 (e.g. typo 'frist') 也走兜底排到 judge 之后"""
    roles = [
        make_role("Judge", "judge"),
        make_role("打错字", "frist"),  # typo
        make_role("一辩", "first"),
    ]
    out = sort_roles_by_debate_position(roles)
    assert [r.name for r in out] == ["一辩", "Judge", "打错字"]


def test_sort_is_stable_for_multiple_unknown_positions():
    """多个未填 position 角色保持原顺序 (Python sorted 是 stable)"""
    roles = [
        make_role("A", ""),
        make_role("B", ""),
        make_role("C", "first"),
    ]
    out = sort_roles_by_debate_position(roles)
    assert [r.name for r in out] == ["C", "A", "B"]


# ── 3. 纯函数: 不修改输入 ──────────────────────────────────

def test_sort_does_not_mutate_input_list():
    """排序不应修改原 list (避免破坏调用方对 _roles 顺序的假设)"""
    roles = [
        make_role("Judge", "judge"),
        make_role("一辩", "first"),
        make_role("二辩", "second"),
    ]
    original_order = [r.name for r in roles]
    _ = sort_roles_by_debate_position(roles)
    assert [r.name for r in roles] == original_order


# ── 4. 稳定性: 多次调用结果一致 ───────────────────────────

def test_sort_idempotent():
    """同一输入多次调用结果一致"""
    roles = [
        make_role("Judge", "judge"),
        make_role("一辩", "first"),
        make_role("二辩", "second"),
        make_role("三辩", "third"),
    ]
    out1 = [r.name for r in sort_roles_by_debate_position(roles)]
    out2 = [r.name for r in sort_roles_by_debate_position(roles)]
    out3 = [r.name for r in sort_roles_by_debate_position(roles)]
    assert out1 == out2 == out3
