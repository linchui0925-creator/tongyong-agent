"""Runtime tool context shared by one streaming request.

Tools should not infer the current chat session from global AgentEngine state.
The streaming entrypoints set these context variables before executing tools so
session-scoped tools can isolate their filesystem workspace and approval queue.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional, Any, Dict


_CURRENT_SESSION_ID: ContextVar[Optional[str]] = ContextVar("tool_session_id", default=None)
_CURRENT_TURN_STRATEGY: ContextVar[Optional[Dict[str, Any]]] = ContextVar("tool_turn_strategy", default=None)


def set_tool_session_id(session_id: Optional[str]):
    return _CURRENT_SESSION_ID.set(session_id)


def reset_tool_session_id(token) -> None:
    _CURRENT_SESSION_ID.reset(token)


def get_tool_session_id(default: str = "default") -> str:
    return _CURRENT_SESSION_ID.get() or default


def set_tool_turn_strategy(strategy: Optional[Dict[str, Any]]):
    return _CURRENT_TURN_STRATEGY.set(strategy)


def reset_tool_turn_strategy(token) -> None:
    _CURRENT_TURN_STRATEGY.reset(token)


def get_tool_turn_strategy(default: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    return _CURRENT_TURN_STRATEGY.get() or default
