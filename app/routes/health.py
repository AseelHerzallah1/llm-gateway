"""Health check endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.version import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe — confirms the gateway process is running."""
    return HealthResponse(status="ok", version=__version__)
