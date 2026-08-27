"""Prometheus metrics exposition endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
from app.observability.prometheus_metrics import get_prometheus_metrics

router = APIRouter(tags=["prometheus"])


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Operational metrics for Prometheus scraping (unauthenticated; internal use only)."""
    if not settings.prometheus_enabled:
        return Response(status_code=404, content="Prometheus metrics are disabled.")

    payload = generate_latest(get_prometheus_metrics().registry)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
