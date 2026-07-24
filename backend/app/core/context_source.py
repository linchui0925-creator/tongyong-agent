"""Context source abstractions for agent runtime.

This module introduces a lightweight, composable model for assembling the
system context from multiple stable sources. It is intentionally small so the
existing prompt assembly flow can migrate incrementally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Optional, List, Dict, Iterable


@dataclass(frozen=True)
class ContextSource:
    """A single stable source of system-context text."""

    key: str
    order: int
    render: str
    source_type: str = "static"
    removable: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)


class ContextSourceProvider(Protocol):
    """Provider interface for dynamic context sources."""

    def get_sources(self, session_id: Optional[str] = None) -> List[ContextSource]:
        ...


class ContextSnapshot:
    """Immutable snapshot of rendered context sources."""

    def __init__(self, sources: Iterable[ContextSource]):
        ordered = sorted(list(sources), key=lambda s: (s.order, s.key))
        self.sources = ordered
        self._by_key = {src.key: src for src in ordered}

    def keys(self) -> List[str]:
        return [src.key for src in self.sources]

    def render(self) -> str:
        return "\n\n".join(src.render for src in self.sources if src.render)

    def diff(self, other: "ContextSnapshot") -> List[ContextSource]:
        changed: List[ContextSource] = []
        for src in self.sources:
            prev = other._by_key.get(src.key)
            if prev is None or prev.render != src.render:
                changed.append(src)
        return changed
