"""Standard tool settlement structures.

These helpers separate the model-visible preview from the durable full result,
so tool output can be handled consistently across providers and UIs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolSettlement:
    tool_name: str
    tool_call_id: str
    success: bool
    preview: str = ""
    full_result: str = ""
    error: str = ""
    error_type: str = ""
    suggestion: str = ""
    emoji: str = ""
    elapsed: float = 0.0
    artifact_previews: List[Dict[str, Any]] = field(default_factory=list)
    managed_output_path: Optional[str] = None

    def to_message_payload(self) -> Dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "emoji": self.emoji,
            "success": self.success,
            "content": self.preview,
            "result_full": self.full_result,
            "error": self.error if not self.success else "",
            "error_type": self.error_type if not self.success else "",
            "suggestion": self.suggestion if not self.success else "",
            "elapsed": round(float(self.elapsed or 0.0), 4),
            "artifact_previews": self.artifact_previews,
            "managed_output_path": self.managed_output_path,
        }
