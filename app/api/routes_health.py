"""Health and UI root routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.api.deps import UI_DIR

router = APIRouter(tags=["health"])


@router.get("/", response_class=HTMLResponse)
async def root() -> FileResponse:
    """Serve the trace viewer UI."""
    return FileResponse(UI_DIR / "index.html")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-finance"}
