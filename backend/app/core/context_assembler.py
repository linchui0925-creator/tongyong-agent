"""Context assembly pipeline for agent turns.

This module turns multiple context sources into a traceable snapshot with
provenance metadata so each turn can be replayed and audited.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from app.core.context_source import ContextSource, ContextSnapshot


@dataclass(frozen=True)
class ContextTraceItem:
    key: str
    order: int
    source_type: str
    render_chars: int
    removable: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextAssemblyResult:
    snapshot: ContextSnapshot
    trace_items: List[ContextTraceItem]

    def keys(self) -> List[str]:
        return self.snapshot.keys()


class ContextAssembler:
    """Deterministically assemble context sources into a snapshot."""

    def __init__(self, sources: Optional[Iterable[ContextSource]] = None):
        self._sources: List[ContextSource] = list(sources or [])

    def add(self, source: ContextSource) -> None:
        self._sources.append(source)

    def extend(self, sources: Iterable[ContextSource]) -> None:
        self._sources.extend(list(sources))

    def build(self) -> ContextAssemblyResult:
        snapshot = ContextSnapshot(self._sources)
        trace_items = [
            ContextTraceItem(
                key=src.key,
                order=src.order,
                source_type=src.source_type,
                render_chars=len(src.render or ""),
                removable=src.removable,
                metadata=dict(src.metadata),
            )
            for src in snapshot.sources
        ]
        return ContextAssemblyResult(snapshot=snapshot, trace_items=trace_items)
