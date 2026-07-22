"""ML anomaly review-queue routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["anomaly"])


class AnomalyResolveResponse(BaseModel):
    session_id: str
    status: str
    action: str
    vendor_name: str
    amount: float
    anomaly_score: float
    explanation: str


@router.get("/anomaly/{session_id}")
async def get_anomaly_review(session_id: str) -> dict:
    from app.human_loop.review_queue import anomaly_review_queue

    item = anomaly_review_queue.get(session_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No anomaly review for session")
    return item.to_public_dict()


@router.post("/anomaly/approve/{session_id}", response_model=AnomalyResolveResponse)
async def approve_anomaly(session_id: str) -> AnomalyResolveResponse:
    from app.human_loop.review_queue import anomaly_review_queue

    try:
        item = await asyncio.to_thread(anomaly_review_queue.resolve, session_id, "approve")
    except KeyError:
        raise HTTPException(status_code=404, detail="No anomaly review for session")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return AnomalyResolveResponse(
        session_id=item.session_id,
        status=item.status,
        action="approve",
        vendor_name=item.vendor_name,
        amount=item.amount,
        anomaly_score=item.anomaly_score,
        explanation=item.explanation,
    )


@router.post("/anomaly/deny/{session_id}", response_model=AnomalyResolveResponse)
async def deny_anomaly(session_id: str) -> AnomalyResolveResponse:
    from app.human_loop.review_queue import anomaly_review_queue

    try:
        item = await asyncio.to_thread(anomaly_review_queue.resolve, session_id, "deny")
    except KeyError:
        raise HTTPException(status_code=404, detail="No anomaly review for session")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return AnomalyResolveResponse(
        session_id=item.session_id,
        status=item.status,
        action="deny",
        vendor_name=item.vendor_name,
        amount=item.amount,
        anomaly_score=item.anomaly_score,
        explanation=item.explanation,
    )
