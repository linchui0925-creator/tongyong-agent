"""
attachment_tools - Read uploaded chat attachments on demand.
"""
from __future__ import annotations

import json
from typing import Optional

from app.api.attachments import get_attachment_metadata, get_attachments_metadata
from app.tools.registry import registry


ATTACHMENT_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "attachment_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要查看的附件 ID 列表；通常来自当前用户消息上下文。",
        },
    },
    "required": ["attachment_ids"],
}


ATTACHMENT_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "attachment_id": {"type": "string", "description": "附件 ID。"},
        "offset": {"type": "integer", "description": "起始字符偏移，默认 0。", "default": 0},
        "limit": {"type": "integer", "description": "最多返回字符数，默认 20000。", "default": 20000},
    },
    "required": ["attachment_id"],
}


def attachment_list(attachment_ids: list[str]) -> str:
    items = get_attachments_metadata(attachment_ids)
    compact = []
    for item in items:
        compact.append({
            "id": item.get("id"),
            "name": item.get("name") or item.get("filename"),
            "mime_type": item.get("mime_type"),
            "kind": item.get("kind"),
            "size": item.get("size"),
            "url": item.get("url"),
            "extraction_status": item.get("extraction_status"),
            "extraction_summary": item.get("extraction_summary"),
            "extraction_error": item.get("extraction_error"),
            "extraction_meta": item.get("extraction_meta"),
        })
    return json.dumps({"attachments": compact}, ensure_ascii=False, indent=2)


def attachment_read(attachment_id: str, offset: int = 0, limit: int = 20_000) -> str:
    item = get_attachment_metadata(attachment_id)
    if not item:
        return f"[error] 附件不存在: {attachment_id}"
    text = item.get("extracted_text") or ""
    if not text:
        status = item.get("extraction_status") or "unknown"
        summary = item.get("extraction_summary") or ""
        error = item.get("extraction_error") or ""
        return json.dumps({
            "id": attachment_id,
            "status": status,
            "summary": summary,
            "error": error,
            "message": "该附件没有可读取正文；只能使用元数据/链接，不能假装读过内容。",
        }, ensure_ascii=False, indent=2)
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 20_000), 80_000))
    chunk = text[offset:offset + limit]
    return json.dumps({
        "id": attachment_id,
        "name": item.get("name") or item.get("filename"),
        "offset": offset,
        "limit": limit,
        "returned_chars": len(chunk),
        "total_chars": len(text),
        "content": chunk,
        "has_more": offset + len(chunk) < len(text),
    }, ensure_ascii=False, indent=2)


def _register_tools():
    registry.register(
        name="attachment_list",
        toolset="attachment",
        description="查看当前消息附件的元数据和解析状态。",
        schema=ATTACHMENT_LIST_SCHEMA,
        handler=attachment_list,
        is_async=False,
        emoji="📎",
        parallel_mode="safe",
    )
    registry.register(
        name="attachment_read",
        toolset="attachment",
        description="按需读取已上传附件的抽取正文。PDF、文本、CSV/Excel、docx/pptx 等附件优先用它读取。",
        schema=ATTACHMENT_READ_SCHEMA,
        handler=attachment_read,
        is_async=False,
        emoji="📎",
        max_result_size_chars=90_000,
        parallel_mode="safe",
    )


_register_tools()
