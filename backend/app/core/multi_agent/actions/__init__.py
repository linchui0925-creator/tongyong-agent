"""
Action System - Multi-Agent 行为单元

基类 + 注册表 + 内置实现。
新增 Action: 在对应文件中添加类 → 在 registry.py 中注册。
"""

from app.core.multi_agent.actions.base import TeamAction, LLMError, _get_llm_for_role, _call_llm
from app.core.multi_agent.actions.registry import get_action_class, list_action_types, create_action

__all__ = [
    "TeamAction", "LLMError",
    "_get_llm_for_role", "_call_llm",
    "get_action_class", "list_action_types", "create_action",
]
