"""
Attachment processor for chat uploads.

This module extracts bounded, prompt-safe text from uploaded files. It is a
read harness only: no OCR, no model calls, no generated examples.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import base64
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Iterable, Optional, Tuple
from zipfile import BadZipFile

from app.services.ocr_service import extract_text_from_image, is_ocr_available
from app.services.document_parser import (
    parse_pdf, parse_docx, parse_xlsx, parse_pptx, parse_text_file, parse_csv,
    _pdf_available, _docx_available, _xlsx_available, _pptx_available
)


MAX_EXTRACTED_CHARS = 120_000
MAX_PROMPT_CHARS = 12_000
MAX_TABLE_ROWS = 40
MAX_TABLE_COLS = 12


@dataclass
class AttachmentExtraction:
    status: str
    text: str = ""
    summary: str = ""
    details: Optional[dict] = None
    error: Optional[str] = None

    def to_record(self) -> dict:
        return {
            "status": self.status,
            "text": self.text,
            "summary": self.summary,
            "details": self.details or {},
            "error": self.error,
        }


def ensure_extraction_columns(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(attachments)").fetchall()
        }
        additions = {
            "extracted_text": "TEXT",
            "extraction_summary": "TEXT",
            "extraction_status": "TEXT NOT NULL DEFAULT 'pending'",
            "extraction_error": "TEXT",
            "extraction_meta": "TEXT",
        }
        for column, ddl in additions.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE attachments ADD COLUMN {column} {ddl}")
        conn.commit()


def extract_attachment(path: Path, mime_type: str, filename: str) -> AttachmentExtraction:
    mime = (mime_type or "").lower()
    suffix = Path(filename).suffix.lower()
    try:
        if mime.startswith("text/") or mime == "application/json" or suffix in {".md", ".txt", ".json"}:
            return _extract_text(path, mime)
        if mime in {"text/csv", "text/tab-separated-values"} or suffix in {".csv", ".tsv"}:
            return _extract_csv(path, delimiter="\t" if suffix == ".tsv" else None)
        if mime == "application/pdf" or suffix == ".pdf":
            return _extract_pdf(path)
        if suffix in {".xlsx", ".xls"} or "spreadsheet" in mime or "excel" in mime:
            return _extract_excel(path)
        if suffix == ".docx" or mime.endswith("wordprocessingml.document"):
            return _extract_docx(path)
        if suffix == ".pptx" or mime.endswith("presentationml.presentation"):
            return _extract_pptx(path)
        if mime.startswith("image/"):
            # 先尝试OCR识别文字
            ocr_text = None
            if is_ocr_available():
                ocr_text = extract_text_from_image(path)
            
            if ocr_text:
                return AttachmentExtraction(
                    status="ocr_extracted",
                    text=ocr_text,
                    summary=f"图片附件已上传，OCR识别出文字内容，共{len(ocr_text)}字符。",
                    details={"kind": "image", "ocr": True, "text_length": len(ocr_text)},
                )
            else:
                return AttachmentExtraction(
                    status="metadata_only",
                    summary="图片附件已上传；未检测到可识别文字，已提供文件链接。如果当前模型支持多模态，会自动发送图片内容进行理解。",
                    details={"kind": "image", "ocr": False},
                )
        return AttachmentExtraction(
            status="unsupported",
            summary="该附件类型暂不支持正文抽取，仅提供元数据。",
            details={"mime_type": mime_type, "filename": filename},
        )
    except Exception as exc:
        return AttachmentExtraction(status="error", error=str(exc), summary=f"附件解析失败: {exc}")


def format_attachment_context(items: Iterable[dict], max_chars: int = MAX_PROMPT_CHARS) -> str:
    lines: list[str] = []
    used = 0
    for item in items:
        header = (
            f"- {item.get('name') or item.get('filename') or 'attachment'} "
            f"({item.get('kind') or 'file'}, {item.get('mime_type') or 'application/octet-stream'}, "
            f"{item.get('size') or 0} bytes, attachment_id={item.get('id') or ''}, url={item.get('url') or ''})"
        )
        lines.append(header)
        for key, label in (
            ("extraction_status", "解析状态"),
            ("extraction_summary", "摘要"),
            ("extraction_error", "错误"),
        ):
            value = (item.get(key) or "").strip()
            if value:
                lines.append(f"  {label}: {value}")
        text = (item.get("extracted_text") or "").strip()
        if text:
            remaining = max_chars - used
            if remaining <= 0:
                lines.append("  正文: ...（附件正文上下文已截断，可用 attachment_read 按需读取）")
                continue
            snippet = text[:remaining]
            used += len(snippet)
            suffix = "\n  ...（已截断，可用 attachment_read 读取更多）" if len(text) > len(snippet) else ""
            lines.append("  正文预览:\n" + _indent(snippet) + suffix)
    return "\n".join(lines)


def _extract_text(path: Path, mime_type: str) -> AttachmentExtraction:
    text = path.read_text(encoding="utf-8", errors="replace")
    if mime_type == "application/json" or path.suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
            text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            pass
    text = _clip(text, MAX_EXTRACTED_CHARS)
    return AttachmentExtraction(
        status="ok",
        text=text,
        summary=f"已抽取文本，约 {len(text)} 字符。",
        details={"chars": len(text)},
    )


def _extract_csv(path: Path, delimiter: Optional[str] = None) -> AttachmentExtraction:
    raw = path.read_text(encoding="utf-8", errors="replace")
    sample = raw[:4096]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample).delimiter
        except Exception:
            delimiter = ","
    reader = csv.reader(StringIO(raw), delimiter=delimiter)
    rows = []
    for i, row in enumerate(reader):
        if i >= MAX_TABLE_ROWS:
            break
        rows.append(row[:MAX_TABLE_COLS])
    text = _table_to_markdown(rows)
    return AttachmentExtraction(
        status="ok",
        text=text,
        summary=f"已解析表格预览：{len(rows)} 行，最多显示 {MAX_TABLE_COLS} 列。",
        details={"rows_previewed": len(rows), "delimiter": delimiter},
    )


def _extract_pdf(path: Path) -> AttachmentExtraction:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        return AttachmentExtraction(status="error", error=f"PyMuPDF 不可用: {exc}", summary="PDF 解析依赖不可用。")

    doc = fitz.open(str(path))
    chunks = []
    for i, page in enumerate(doc):
        chunks.append(f"\n\n[Page {i + 1}]\n{page.get_text('text')}")
        if sum(len(c) for c in chunks) >= MAX_EXTRACTED_CHARS:
            break
    text = _clip("".join(chunks).strip(), MAX_EXTRACTED_CHARS)
    status = "ok" if text.strip() else "metadata_only"
    summary = (
        f"PDF 共 {doc.page_count} 页，已抽取约 {len(text)} 字符。"
        if text.strip()
        else f"PDF 共 {doc.page_count} 页，但未抽取到文本；可能是扫描版，需要 OCR。"
    )
    return AttachmentExtraction(status=status, text=text, summary=summary, details={"pages": doc.page_count})


def _extract_excel(path: Path) -> AttachmentExtraction:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:
        return AttachmentExtraction(status="error", error=f"pandas/openpyxl 不可用: {exc}", summary="表格解析依赖不可用。")

    sheets = pd.read_excel(path, sheet_name=None, nrows=MAX_TABLE_ROWS, engine=None)
    parts: list[str] = []
    details = {"sheets": []}
    for name, df in sheets.items():
        preview = df.iloc[:, :MAX_TABLE_COLS].fillna("")
        rows = [list(preview.columns)] + preview.astype(str).values.tolist()
        parts.append(f"\n\n[Sheet: {name}]\n{_table_to_markdown(rows)}")
        details["sheets"].append({"name": str(name), "rows_previewed": int(len(preview)), "columns_previewed": int(len(preview.columns))})
    text = _clip("".join(parts).strip(), MAX_EXTRACTED_CHARS)
    return AttachmentExtraction(
        status="ok",
        text=text,
        summary=f"已解析 Excel：{len(sheets)} 个 sheet，正文为前 {MAX_TABLE_ROWS} 行预览。",
        details=details,
    )


def _extract_docx(path: Path) -> AttachmentExtraction:
    try:
        from zipfile import ZipFile
        import xml.etree.ElementTree as ET
        with ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
        texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        return AttachmentExtraction(status="error", error=str(exc), summary="DOCX 解析失败。")
    text = _clip("\n".join(texts), MAX_EXTRACTED_CHARS)
    return AttachmentExtraction(status="ok", text=text, summary=f"已抽取 DOCX 文本，约 {len(text)} 字符。", details={"chars": len(text)})


def _extract_pptx(path: Path) -> AttachmentExtraction:
    try:
        from zipfile import ZipFile
        import xml.etree.ElementTree as ET
        with ZipFile(path) as zf:
            slide_names = sorted(name for name in zf.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            chunks = []
            for idx, slide_name in enumerate(slide_names, 1):
                root = ET.fromstring(zf.read(slide_name))
                texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
                chunks.append(f"\n\n[Slide {idx}]\n" + "\n".join(texts))
    except (BadZipFile, ET.ParseError) as exc:
        return AttachmentExtraction(status="error", error=str(exc), summary="PPTX 解析失败。")
    text = _clip("".join(chunks).strip(), MAX_EXTRACTED_CHARS)
    return AttachmentExtraction(status="ok", text=text, summary=f"已抽取 PPTX：{len(slide_names)} 页幻灯片。", details={"slides": len(slide_names)})


def _table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    normalized = [[str(cell) for cell in row] for row in rows]
    width = max(len(row) for row in normalized)
    normalized = [row + [""] * (width - len(row)) for row in normalized]
    header = normalized[0]
    body = normalized[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n...（内容过长，已截断）"


def _indent(text: str) -> str:
    return "\n".join("  " + line for line in text.splitlines())
