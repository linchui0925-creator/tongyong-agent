"""Provider-neutral request/response contracts for LLM calls.

This module is the first step toward protocol unification:
- request is described once
- provider adapters only translate wire formats
- runtime code consumes normalized results
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class GenerationControls:
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stop: Optional[List[str]] = None


@dataclass(frozen=True)
class ModelRequestOptions:
    model: str
    provider: str
    api_format: str = "chat_completions"
    stream_mode: str = "native"
    controls: GenerationControls = field(default_factory=GenerationControls)
    provider_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelToolCall:
    tool_name: str
    arguments: Dict[str, Any]
    tool_call_id: str = ""


@dataclass(frozen=True)
class ModelThinkingBlock:
    text: str


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: List[ModelToolCall] = field(default_factory=list)
    thinking: List[ModelThinkingBlock] = field(default_factory=list)
    usage: ModelUsage = field(default_factory=ModelUsage)
    raw: Optional[Dict[str, Any]] = None
