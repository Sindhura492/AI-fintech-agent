"""Pipeline run and dispute-resolve routes."""

from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import SAMPLE_DOCS, SAMPLES
from app.core import DisputeRequest, DisputeResponse

router = APIRouter(tags=["pipeline"])


class RunRequest(BaseModel):
    sample_id: Literal["po1001", "po1002", "po1003"] = Field(
        ...,
        description="Which sample invoice to process.",
    )
    session_id: str | None = Field(
        default=None,
        description="Pre-allocated session id (UI should subscribe on /ws first).",
    )


class RunResponse(BaseModel):
    session_id: str
    po_id: str
    file_path: str
    sample_id: str


@router.post("/run", response_model=RunResponse)
async def run_pipeline_endpoint(body: RunRequest) -> RunResponse:
    from app.pipeline.orchestrator import run_pipeline

    filename, po_id = SAMPLES[body.sample_id]
    file_path = str((SAMPLE_DOCS / filename).resolve())
    session_id = body.session_id or str(uuid.uuid4())

    async def _job() -> None:
        try:
            await asyncio.to_thread(
                run_pipeline,
                file_path,
                po_id,
                session_id=session_id,
            )
        except Exception:
            pass

    asyncio.create_task(_job())
    return RunResponse(
        session_id=session_id,
        po_id=po_id,
        file_path=file_path,
        sample_id=body.sample_id,
    )


@router.post("/disputes/resolve", response_model=DisputeResponse)
async def resolve_dispute_endpoint(request: DisputeRequest) -> DisputeResponse:
    from app.pipeline.orchestrator import resolve_dispute

    return await resolve_dispute(request)
