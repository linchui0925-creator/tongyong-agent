"""Local artifact store for traceable turn evidence.

This is the first step toward an object-store abstraction. It writes artifacts
locally now, but keeps stable metadata so the backend can move to OSS later
without changing callers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import json
import hashlib

from app.paths import data_path


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    artifact_type: str
    session_id: str
    turn_id: str
    path: str
    checksum: str
    size_bytes: int
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class LocalArtifactStore:
    """Filesystem-backed artifact store with a stable manifest format."""

    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = Path(root_dir or data_path("artifacts"))
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _artifact_dir(self, session_id: str, turn_id: str, artifact_type: str) -> Path:
        safe_type = artifact_type.replace("/", "_")
        path = self.root_dir / session_id / turn_id / safe_type
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _checksum(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def store_text(
        self,
        *,
        session_id: str,
        turn_id: str,
        artifact_type: str,
        content: str,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        payload = (content or "").encode("utf-8")
        checksum = self._checksum(payload)
        artifact_id = checksum[:16]
        dir_path = self._artifact_dir(session_id, turn_id, artifact_type)
        file_name = filename or f"{artifact_id}.txt"
        file_path = dir_path / file_name
        file_path.write_text(content or "", encoding="utf-8")

        record = ArtifactRecord(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            session_id=session_id,
            turn_id=turn_id,
            path=str(file_path),
            checksum=checksum,
            size_bytes=len(payload),
            created_at=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        self._write_manifest(record)
        return record

    def store_json(
        self,
        *,
        session_id: str,
        turn_id: str,
        artifact_type: str,
        payload: Dict[str, Any],
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return self.store_text(
            session_id=session_id,
            turn_id=turn_id,
            artifact_type=artifact_type,
            content=content,
            filename=filename or "artifact.json",
            metadata=metadata,
        )

    def _write_manifest(self, record: ArtifactRecord) -> None:
        manifest_path = Path(record.path).parent / "manifest.json"
        existing = []
        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8") or "[]")
            except Exception:
                existing = []
        existing.append(asdict(record))
        manifest_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
