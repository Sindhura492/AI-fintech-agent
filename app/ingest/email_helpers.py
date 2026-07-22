"""Small MIME/filename helpers for IMAP ingest."""

from __future__ import annotations

import email
import re
import uuid
from email.header import decode_header, make_header
from pathlib import Path


def _decode_mime_header(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\-]+", "_", base).strip("._")
    return cleaned or f"attachment-{uuid.uuid4().hex}.pdf"


def _is_pdf_part(part: email.message.Message, filename: str, payload: bytes) -> bool:
    ctype = (part.get_content_type() or "").lower()
    if filename.lower().endswith(".pdf"):
        return True
    if ctype == "application/pdf":
        return True
    # Magic-byte fallback when Content-Type / name are wrong.
    return payload[:4] == b"%PDF"

