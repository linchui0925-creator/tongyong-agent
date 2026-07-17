"""
W4-51: Chat attachment upload + safe content serve.

MVP scope:
- Store user-uploaded images/files under backend/data/attachments.
- Expose content by opaque attachment id, never by raw path.
- Return metadata the frontend can render inside chat bubbles.
"""
from __future__ import annotations
from app.paths import data_path

import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.attachment_processor import (
    ensure_extraction_columns,
    extract_attachment,
)


router = APIRouter(prefix="/api/chat/attachments", tags=["chat-attachments"])

_BASE_DIR = Path(os.getenv("ATTACHMENTS_DIR", data_path("attachments"))).resolve()
_DB_PATH = Path(os.getenv("ATTACHMENTS_DB", data_path("attachments.db"))).resolve()
_MAX_FILE_SIZE = int(os.getenv("ATTACHMENTS_MAX_BYTES", str(25 * 1024 * 1024)))
_CHUNK_SIZE = 1024 * 1024

_ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/tab-separated-values",
    "application/json",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _init_db() -> None:
    _BASE_DIR.mkdir(parents=True, exist_ok=True)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.commit()
    ensure_extraction_columns(_DB_PATH)


def _allowed_by_extension(mime_type: str, filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    if mime_type in _ALLOWED_MIME_TYPES:
        return True
    return suffix in {
        ".txt", ".md", ".markdown", ".csv", ".tsv", ".json",
        ".pdf", ".xlsx", ".xls", ".docx", ".pptx",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    }


def _kind_from_name(mime_type: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xls", ".csv", ".tsv"}:
        return "table"
    if suffix in {".docx", ".pptx"}:
        return "document"
    return _detect_kind(mime_type)


def _safe_filename(filename: str) -> str:
    name = Path(filename or "attachment").name.strip() or "attachment"
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:160] or "attachment"


def _detect_kind(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type.startswith("text/") or mime_type == "application/json":
        return "text"
    return "file"


def _normalize_mime(upload: UploadFile, filename: str) -> str:
    mime_type = (upload.content_type or "").split(";")[0].strip().lower()
    if not mime_type or mime_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(filename)
        mime_type = (guessed or "application/octet-stream").lower()
    return mime_type


def _record_to_payload(row: sqlite3.Row) -> dict:
    url = f"/api/chat/attachments/{row['id']}/content"
    extraction_meta = row["extraction_meta"] if "extraction_meta" in row.keys() else None
    try:
        extraction_meta = json.loads(extraction_meta) if extraction_meta else {}
    except Exception:
        extraction_meta = {}
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "filename": row["filename"],
        "name": row["filename"],
        "mime_type": row["mime_type"],
        "size": row["size"],
        "sha256": row["sha256"],
        "kind": row["kind"],
        "url": url,
        "preview_url": url,
        "open_url": url,
        "created_at": row["created_at"],
        "extraction_status": row["extraction_status"] if "extraction_status" in row.keys() else "pending",
        "extraction_summary": row["extraction_summary"] if "extraction_summary" in row.keys() else "",
        "extraction_error": row["extraction_error"] if "extraction_error" in row.keys() else None,
        "extraction_meta": extraction_meta,
        "extracted_text": row["extracted_text"] if "extracted_text" in row.keys() else "",
    }


def _fetch_attachment(attachment_id: str) -> dict:
    _init_db()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "附件不存在")
    return dict(row)


def get_attachment_metadata(attachment_id: str) -> Optional[dict]:
    """Read metadata without raising; used by stream prompt enrichment."""
    _init_db()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
    return _record_to_payload(row) if row else None


def get_attachments_metadata(attachment_ids: Iterable[str]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for attachment_id in attachment_ids:
        if not attachment_id or attachment_id in seen:
            continue
        seen.add(attachment_id)
        item = get_attachment_metadata(attachment_id)
        if item:
            items.append(item)
    return items


@router.post("/upload")
async def upload_attachments(
    files: list[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
):
    if not files:
        raise HTTPException(400, "没有上传文件")

    _init_db()
    stored: list[dict] = []

    for upload in files:
        safe_name = _safe_filename(upload.filename or "attachment")
        mime_type = _normalize_mime(upload, safe_name)
        if not _allowed_by_extension(mime_type, safe_name):
            raise HTTPException(415, f"不支持的文件类型: {mime_type}")

        attachment_id = f"att_{uuid.uuid4().hex}"
        storage_dir = (_BASE_DIR / attachment_id[4:6]).resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = (storage_dir / f"{attachment_id}_{safe_name}").resolve()
        try:
            storage_path.relative_to(_BASE_DIR)
        except ValueError:
            raise HTTPException(400, "非法文件名")

        sha = hashlib.sha256()
        total = 0
        with storage_path.open("wb") as out:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_FILE_SIZE:
                    out.close()
                    storage_path.unlink(missing_ok=True)
                    raise HTTPException(413, "文件超过大小限制")
                sha.update(chunk)
                out.write(chunk)

        kind = _kind_from_name(mime_type, safe_name)
        extraction = extract_attachment(storage_path, mime_type, safe_name).to_record()
        created_at = time.time()
        payload = {
            "id": attachment_id,
            "session_id": session_id,
            "filename": safe_name,
            "name": safe_name,
            "mime_type": mime_type,
            "size": total,
            "sha256": sha.hexdigest(),
            "kind": kind,
            "url": f"/api/chat/attachments/{attachment_id}/content",
            "preview_url": f"/api/chat/attachments/{attachment_id}/content",
            "open_url": f"/api/chat/attachments/{attachment_id}/content",
            "created_at": created_at,
            "extraction_status": extraction["status"],
            "extraction_summary": extraction["summary"],
            "extraction_error": extraction["error"],
            "extraction_meta": extraction["details"],
            "extracted_text": extraction["text"],
        }

        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO attachments
                    (
                        id, session_id, filename, mime_type, size, sha256, storage_path, kind, created_at,
                        extracted_text, extraction_summary, extraction_status, extraction_error, extraction_meta
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    session_id,
                    safe_name,
                    mime_type,
                    total,
                    payload["sha256"],
                    str(storage_path),
                    kind,
                    created_at,
                    extraction["text"],
                    extraction["summary"],
                    extraction["status"],
                    extraction["error"],
                    json.dumps(extraction["details"], ensure_ascii=False),
                ),
            )
            conn.commit()

        stored.append(payload)

    return {"attachments": stored}


@router.get("/{attachment_id}/meta")
async def attachment_meta(attachment_id: str):
    row = _fetch_attachment(attachment_id)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        payload_row = conn.execute(
            "SELECT * FROM attachments WHERE id = ?",
            (row["id"],),
        ).fetchone()
    return _record_to_payload(payload_row)


@router.get("/{attachment_id}/content")
async def attachment_content(attachment_id: str):
    row = _fetch_attachment(attachment_id)
    path = Path(row["storage_path"]).resolve()
    try:
        path.relative_to(_BASE_DIR)
    except ValueError:
        raise HTTPException(403, "附件路径非法")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "附件文件不存在")

    headers = {
        "Content-Disposition": f'inline; filename="{row["filename"]}"',
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(path, media_type=row["mime_type"], filename=row["filename"], headers=headers)
