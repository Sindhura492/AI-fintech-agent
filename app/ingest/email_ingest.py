"""Gmail IMAP ingest — save raw PDF attachments for sandboxed parsing."""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import re
import uuid
from email.header import decode_header, make_header
from pathlib import Path

from app.config import get_settings
from app.ingest.email_helpers import (
    _decode_mime_header,
    _is_pdf_part,
    _safe_filename,
)

logger = logging.getLogger(__name__)

# Raw bytes land here — still untrusted until the sandbox reads them.
INCOMING_DIR = Path("/tmp/incoming")
DEFAULT_IMAP_HOST = "imap.gmail.com"
DEFAULT_IMAP_PORT = 993
POLL_INTERVAL_SECONDS = 15.0

# Process-local inbox stats for the live UI indicator.
_inbox_listening = False
_emails_processed = 0
_last_session_id: str | None = None
_last_sender: str | None = None

def get_inbox_stats() -> dict[str, str | int | bool | None]:
    """Snapshot for GET /inbox/status (UI poll)."""
    return {
        "listening": _inbox_listening,
        "emails_processed": _emails_processed,
        "last_session_id": _last_session_id,
        "last_sender": _last_sender,
    }

def _record_processed(session_id: str, sender: str) -> None:
    global _emails_processed, _last_session_id, _last_sender
    _emails_processed += 1
    _last_session_id = session_id
    _last_sender = sender

def _require_credentials() -> tuple[str, str]:
    s = get_settings()
    address = (s.email_address or "").strip()
    password = (s.email_app_password or "").strip()
    if not address or not password:
        raise RuntimeError(
            "EMAIL_ADDRESS and EMAIL_APP_PASSWORD must be set in .env "
            "(use a Gmail App Password, not your normal login password)."
        )
    return address, password

def _imap_host() -> str:
    host = (get_settings().email_imap_host or DEFAULT_IMAP_HOST).strip()
    return host or DEFAULT_IMAP_HOST

def _connect() -> imaplib.IMAP4_SSL:
    address, password = _require_credentials()
    host = _imap_host()
    try:
        client = imaplib.IMAP4_SSL(host, DEFAULT_IMAP_PORT)
        client.login(address, password)
        return client
    except Exception as exc:
        # imaplib may echo credentials in raw error text — never re-raise as-is.
        raise RuntimeError(
            f"IMAP connection/login failed for user={address!r} host={host!r}: "
            f"{type(exc).__name__} (details redacted)"
        ) from None

def fetch_unread_invoices() -> list[dict]:
    """Fetch UNSEEN Gmail messages and save PDF attachments under /tmp/incoming/.

    Connects via IMAP using ``EMAIL_ADDRESS`` / ``EMAIL_APP_PASSWORD``.
    For each unread message, extracts sender, subject, and any PDF attachments
    (raw bytes only — no PDF parsing here).

    Messages are fetched with BODY.PEEK so they stay UNSEEN until
    ``mark_email_seen`` runs after a successful pipeline handoff. A crash
    mid-processing therefore leaves the email unread for retry.

    Returns:
        List of dicts::

            {
              "uid": str,
              "sender": str,
              "subject": str,
              "pdf_paths": list[str],  # absolute paths under /tmp/incoming/
            }

        Emails with no PDF attachments are included with an empty pdf_paths
        list so the poller can decide how to handle them.
    """
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)

    client = _connect()
    results: list[dict] = []
    try:
        typ, _ = client.select("INBOX")
        if typ != "OK":
            raise RuntimeError("IMAP SELECT INBOX failed")

        # UID SEARCH keeps stable ids across the session.
        typ, data = client.uid("search", None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return []

        uids = data[0].split()
        for uid in uids:
            uid_str = uid.decode("ascii") if isinstance(uid, bytes) else str(uid)
            # PEEK = do not set \\Seen on fetch.
            typ, fetched = client.uid("fetch", uid_str, "(BODY.PEEK[])")
            if typ != "OK" or not fetched or fetched[0] is None:
                logger.warning("Failed to fetch uid=%s", uid_str)
                continue

            raw_email = fetched[0][1]
            if not isinstance(raw_email, (bytes, bytearray)):
                continue

            msg = email.message_from_bytes(raw_email)
            sender = _decode_mime_header(msg.get("From"))
            subject = _decode_mime_header(msg.get("Subject"))
            pdf_paths: list[str] = []

            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                disposition = str(part.get("Content-Disposition") or "")
                filename = part.get_filename()
                if filename:
                    filename = _decode_mime_header(filename)
                # Only consider explicit attachments / named parts.
                if "attachment" not in disposition.lower() and not filename:
                    continue

                payload = part.get_payload(decode=True)
                if not isinstance(payload, (bytes, bytearray)) or not payload:
                    continue
                payload_bytes = bytes(payload)
                name = filename or "attachment.pdf"
                if not _is_pdf_part(part, name, payload_bytes):
                    continue

                # Save raw bytes only — never open/parse the PDF here.
                out_name = f"{uid_str}_{_safe_filename(name)}"
                if not out_name.lower().endswith(".pdf"):
                    out_name += ".pdf"
                out_path = INCOMING_DIR / out_name
                out_path.write_bytes(payload_bytes)
                pdf_paths.append(str(out_path.resolve()))
                logger.info(
                    "Saved untrusted PDF attachment uid=%s path=%s bytes=%d",
                    uid_str,
                    out_path,
                    len(payload_bytes),
                )

            results.append(
                {
                    "uid": uid_str,
                    "sender": sender,
                    "subject": subject,
                    "pdf_paths": pdf_paths,
                }
            )
    finally:
        try:
            client.logout()
        except Exception:
            pass

    return results

def mark_email_seen(uid: str) -> None:
    """Mark a message \\Seen after successful pipeline handoff."""
    client = _connect()
    try:
        typ, _ = client.select("INBOX")
        if typ != "OK":
            raise RuntimeError("IMAP SELECT INBOX failed")
        typ, _ = client.uid("store", uid, "+FLAGS", "(\\Seen)")
        if typ != "OK":
            raise RuntimeError(f"Failed to mark uid={uid} as Seen")
        logger.info("Marked email uid=%s as Seen", uid)
    finally:
        try:
            client.logout()
        except Exception:
            pass

async def poll_inbox_loop(interval: float = POLL_INTERVAL_SECONDS) -> None:
    """Poll Gmail every ``interval`` seconds and hand PDFs to the pipeline.

    For each unread email with PDF attachments, calls
    ``orchestrator.run_pipeline_from_email(file_path, sender_email)``.

    Emails are marked read only after every PDF for that message has been
    successfully handed off (pipeline returned without raising).
    """
    global _inbox_listening
    from app.pipeline.orchestrator import run_pipeline_from_email

    _inbox_listening = True
    logger.info(
        "Starting inbox poll loop (every %.0fs). "
        "Attachments are untrusted input — sandbox parses them later.",
        interval,
    )

    while True:
        try:
            items = await asyncio.to_thread(fetch_unread_invoices)
            if items:
                logger.info("Fetched %d unread message(s)", len(items))

            for item in items:
                uid = item["uid"]
                paths: list[str] = item.get("pdf_paths") or []
                sender = item.get("sender") or ""

                if not paths:
                    logger.info(
                        "uid=%s from=%r subject=%r has no PDF — leaving unread",
                        uid,
                        sender,
                        item.get("subject"),
                    )
                    continue

                handoff_ok = True
                for file_path in paths:
                    try:
                        logger.info(
                            "Handoff to run_pipeline_from_email uid=%s file=%s sender=%r",
                            uid,
                            file_path,
                            sender,
                        )
                        result = await asyncio.to_thread(
                            lambda fp=file_path: run_pipeline_from_email(
                                fp,
                                sender,
                            )
                        )
                        _record_processed(
                            str(result.get("session_id") or ""),
                            sender,
                        )
                        if result.get("status") == "needs_manual_po_matching":
                            logger.warning(
                                "uid=%s no matching PO — escalated session=%s",
                                uid,
                                result.get("session_id"),
                            )
                    except Exception:
                        handoff_ok = False
                        logger.exception(
                            "Pipeline failed for uid=%s file=%s — "
                            "email stays UNSEEN for retry",
                            uid,
                            file_path,
                        )

                if handoff_ok:
                    try:
                        await asyncio.to_thread(mark_email_seen, uid)
                    except Exception:
                        logger.exception(
                            "Pipeline succeeded but mark_email_seen failed uid=%s",
                            uid,
                        )
        except Exception:
            # Avoid logger.exception here — raw IMAP errors can embed credentials.
            logger.error(
                "poll_inbox_loop iteration failed: %s",
                "IMAP/pipeline error (details redacted — check credentials in .env)",
            )

        await asyncio.sleep(interval)
