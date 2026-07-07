"""Homepage contact form submissions.

Stores submissions in a small SQLite table (`data/contact.db`) and sends each
submission to the configured notification inbox.
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
import sqlite3
import time
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contact", tags=["contact"])

_DB_PATH = Path(os.getenv("CONTACT_DB", "./data/contact.db")).resolve()
_DEFAULT_EMAIL_TO = "xiying236848@gmail.com"

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ALLOWED_TOPICS = {"cooperation", "support", "feedback", "other"}
TOPIC_LABELS = {
    "cooperation": "合作咨询",
    "support": "技术支持",
    "feedback": "功能建议",
    "other": "其他",
}


class ContactSubmission(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(min_length=3, max_length=120)
    topic: Literal["cooperation", "support", "feedback", "other"]
    message: str = Field(min_length=10, max_length=2000)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        if not EMAIL_RE.match(v.strip()):
            raise ValueError("邮箱格式不正确")
        return v.strip()

    @field_validator("name")
    @classmethod
    def _trim_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("message")
    @classmethod
    def _trim_message(cls, v: str) -> str:
        return v.strip()


class ContactSubmissionAck(BaseModel):
    id: str
    received_at: float
    topic: str


def _ensure_schema() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_submissions (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                email       TEXT NOT NULL,
                topic       TEXT NOT NULL,
                message     TEXT NOT NULL,
                ip          TEXT,
                user_agent  TEXT,
                received_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contact_received_at ON contact_submissions(received_at DESC)"
        )
        conn.commit()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_email_message(
    payload: ContactSubmission,
    *,
    submission_id: str,
    received_at: float,
    recipient: str,
    sender: str,
    ip: str | None,
    user_agent: str | None,
) -> EmailMessage:
    topic_label = TOPIC_LABELS.get(payload.topic, payload.topic)
    received = datetime.fromtimestamp(received_at).strftime("%Y-%m-%d %H:%M:%S")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Reply-To"] = payload.email
    message["Subject"] = f"[TongYong 首页联系] {topic_label} - {payload.name}"
    message.set_content(
        "\n".join(
            [
                "收到新的首页联系表单提交。",
                "",
                f"提交 ID: {submission_id}",
                f"收到时间: {received}",
                f"姓名: {payload.name}",
                f"邮箱: {payload.email}",
                f"主题: {topic_label}",
                f"IP: {ip or '-'}",
                f"User-Agent: {user_agent or '-'}",
                "",
                "详细描述:",
                payload.message,
            ]
        )
    )
    return message


def _send_submission_email(
    payload: ContactSubmission,
    *,
    submission_id: str,
    received_at: float,
    ip: str | None,
    user_agent: str | None,
) -> None:
    recipient = os.getenv("CONTACT_EMAIL_TO", _DEFAULT_EMAIL_TO).strip()
    host = os.getenv("CONTACT_SMTP_HOST") or os.getenv("SMTP_HOST")
    username = os.getenv("CONTACT_SMTP_USERNAME") or os.getenv("SMTP_USERNAME")
    password = os.getenv("CONTACT_SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD")
    sender = (
        os.getenv("CONTACT_SMTP_FROM")
        or os.getenv("SMTP_FROM")
        or username
        or "TongYong Agent <noreply@localhost>"
    )
    port = int(os.getenv("CONTACT_SMTP_PORT") or os.getenv("SMTP_PORT") or "587")
    timeout = float(os.getenv("CONTACT_SMTP_TIMEOUT", "10"))
    use_ssl = _env_bool("CONTACT_SMTP_SSL", port == 465)
    use_tls = _env_bool("CONTACT_SMTP_TLS", not use_ssl)

    missing = [
        name
        for name, value in {
            "CONTACT_SMTP_HOST": host,
            "CONTACT_SMTP_USERNAME": username,
            "CONTACT_SMTP_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"邮件服务未配置: 请设置 {', '.join(missing)}")

    message = _build_email_message(
        payload,
        submission_id=submission_id,
        received_at=received_at,
        recipient=recipient,
        sender=sender,
        ip=ip,
        user_agent=user_agent,
    )

    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(host, port, timeout=timeout) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


@router.post("", response_model=ContactSubmissionAck)
async def submit_contact(payload: ContactSubmission, request: Request) -> ContactSubmissionAck:
    if payload.topic not in ALLOWED_TOPICS:
        raise HTTPException(status_code=422, detail="不支持的主题")
    _ensure_schema()
    sid = uuid.uuid4().hex
    now = time.time()
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    try:
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute(
                """
                INSERT INTO contact_submissions
                    (id, name, email, topic, message, ip, user_agent, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, payload.name, payload.email, payload.topic, payload.message, ip, user_agent, now),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.exception("contact submit failed: %s", e)
        raise HTTPException(status_code=500, detail="提交失败，请稍后再试") from e
    try:
        _send_submission_email(
            payload,
            submission_id=sid,
            received_at=now,
            ip=ip,
            user_agent=user_agent,
        )
    except Exception as e:
        logger.exception("contact email delivery failed: %s", e)
        raise HTTPException(status_code=500, detail="提交已保存，但邮件发送失败，请检查邮件服务配置") from e
    logger.info(
        "contact submission id=%s topic=%s email=%s name=%s notified=%s",
        sid, payload.topic, payload.email, payload.name, os.getenv("CONTACT_EMAIL_TO", _DEFAULT_EMAIL_TO),
    )
    return ContactSubmissionAck(id=sid, received_at=now, topic=payload.topic)


@router.get("/count")
async def submissions_count() -> dict:
    """Tiny endpoint for ops to confirm the DB is reachable. Not part of the
    public-facing UI; useful for health pings."""
    if not _DB_PATH.exists():
        return {"count": 0}
    try:
        with sqlite3.connect(str(_DB_PATH)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM contact_submissions").fetchone()
            return {"count": int(row[0]) if row else 0}
    except sqlite3.Error:
        return {"count": 0}
