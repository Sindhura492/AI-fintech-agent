"""Metrics API routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> dict:
    from app.observability.monitoring import metrics_store

    return await asyncio.to_thread(metrics_store.summary)


@router.get("/metrics/history")
async def metrics_history(
    since: str | None = None,
    limit: int = 500,
) -> dict:
    from app.observability.monitoring import metrics_store

    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=400, detail="limit must be 1..5000")

    rows = await asyncio.to_thread(
        lambda: metrics_store.history(since=since, limit=limit)
    )
    return {
        "db_path": metrics_store.absolute_path(),
        "since": since,
        "count": len(rows),
        "rows": rows,
    }
