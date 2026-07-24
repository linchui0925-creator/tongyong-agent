"""Runtime snapshot for a single agent turn.

The goal is to make the current model / agent / tool-policy combination explicit
instead of spread across loosely related singletons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.context_source import ContextSnapshot
from app.core.context_assembler import ContextTraceItem


@dataclass(frozen=True)
class AgentRuntimeState:
    provider: str
    model: str
    agent_name: str
    tool_policy: str
    session_id: str
    api_format: str = "chat_completions"
    stream_mode: str = "native"
    request_config: Dict[str, Any] = field(default_factory=dict)
    provider_profile_id: Optional[str] = None
    trace_id: Optional[str] = None
    turn_index: int = 0
    context_epoch: int = 0
    prompt_revision: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTurnState:
    runtime: AgentRuntimeState
    context_snapshot: Optional[ContextSnapshot] = None
    context_trace: List[ContextTraceItem] = field(default_factory=list)
    prompt_revision: int = 0
    turn_stage: str = "preflight"
    tool_round: int = 0
    model_call_count: int = 0
    finalized: bool = False

    def describe(self) -> Dict[str, Any]:
        return {
            "provider": self.runtime.provider,
            "model": self.runtime.model,
            "agent_name": self.runtime.agent_name,
            "tool_policy": self.runtime.tool_policy,
            "session_id": self.runtime.session_id,
            "api_format": self.runtime.api_format,
            "stream_mode": self.runtime.stream_mode,
            "provider_profile_id": self.runtime.provider_profile_id,
            "trace_id": self.runtime.trace_id,
            "turn_index": self.runtime.turn_index,
            "context_epoch": self.runtime.context_epoch,
            "prompt_revision": self.prompt_revision,
            "turn_stage": self.turn_stage,
            "tool_round": self.tool_round,
            "model_call_count": self.model_call_count,
            "finalized": self.finalized,
            "context_keys": self.context_snapshot.keys() if self.context_snapshot else [],
            "context_trace": [item.__dict__ for item in self.context_trace],
        }
