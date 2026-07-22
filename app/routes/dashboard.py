"""Serve the minimal observability dashboard."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["dashboard"])

_DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"


@router.get("/dashboard")
async def dashboard_page() -> FileResponse:
    """Single-page dashboard — fetches /v1/metrics and /v1/requests in the browser."""
    return FileResponse(_DASHBOARD_HTML, media_type="text/html")
