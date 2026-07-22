"""Human escalation review routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["escalations"])


class EscalationResolveResponse(BaseModel):
    session_id: str
    status: str
    action: str
    vendor_name: str
    amount: float | None
    reason: str
    payment_executed: bool


@router.get("/escalations/{session_id}")
async def get_escalation(session_id: str) -> dict:
    from app.human_loop.escalations import escalation_store

    case = escalation_store.get(session_id)
    if case is None:
        raise HTTPException(status_code=404, detail="No escalated case for session")
    return case.to_public_dict()


@router.get("/reviews/{session_id}")
async def get_session_reviews(session_id: str) -> dict:
    from app.human_loop.escalations import escalation_store
    from app.human_loop.review_queue import anomaly_review_queue

    items: list[dict] = []
    esc = escalation_store.get(session_id)
    if esc is not None:
        items.append(esc.to_public_dict())
    anom = anomaly_review_queue.get(session_id)
    if anom is not None:
        items.append(anom.to_public_dict())
    return {"session_id": session_id, "items": items}


@router.post("/approve/{session_id}", response_model=EscalationResolveResponse)
async def approve_escalation(session_id: str) -> EscalationResolveResponse:
    from app.human_loop.escalations import escalation_store

    try:
        case = await asyncio.to_thread(escalation_store.resolve, session_id, "approve")
    except KeyError:
        raise HTTPException(status_code=404, detail="No escalated case for session")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return EscalationResolveResponse(
        session_id=case.session_id,
        status=case.status,
        action="approve",
        vendor_name=case.vendor_name,
        amount=case.amount,
        reason=case.reason,
        payment_executed=case.payment_executed,
    )


@router.post("/deny/{session_id}", response_model=EscalationResolveResponse)
async def deny_escalation(session_id: str) -> EscalationResolveResponse:
    from app.human_loop.escalations import escalation_store

    try:
        case = await asyncio.to_thread(escalation_store.resolve, session_id, "deny")
    except KeyError:
        raise HTTPException(status_code=404, detail="No escalated case for session")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return EscalationResolveResponse(
        session_id=case.session_id,
        status=case.status,
        action="deny",
        vendor_name=case.vendor_name,
        amount=case.amount,
        reason=case.reason,
        payment_executed=case.payment_executed,
    )
