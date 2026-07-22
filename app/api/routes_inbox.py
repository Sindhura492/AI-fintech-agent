"""Inbox status and email-session trace routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.observability.audit import audit_log

router = APIRouter(tags=["inbox"])


@router.get("/inbox/status")
async def inbox_status() -> dict[str, str | int | bool | None]:
    from app.ingest.email_ingest import get_inbox_stats

    return get_inbox_stats()


@router.get("/inbox/trace/{session_id}")
async def inbox_trace(session_id: str) -> list[dict]:
    return [e.model_dump(mode="json") for e in audit_log.get_trace(session_id)]
