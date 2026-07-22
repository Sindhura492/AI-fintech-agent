"""Health and UI root routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.api.deps import FRONTEND_DIST, UI_DIR

router = APIRouter(tags=["health"])


@router.get("/", response_class=HTMLResponse)
async def root() -> FileResponse:
    """Serve the React app (frontend/dist) or legacy ui/index.html."""
    react_index = FRONTEND_DIST / "index.html"
    if react_index.is_file():
        return FileResponse(react_index)
    legacy = UI_DIR / "index.html"
    return FileResponse(legacy)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-finance"}
