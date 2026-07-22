"""Metrics routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_project
from app.db.models.project import Project
from app.db.session import get_db
from app.errors import GatewayHTTPException
from app.observability.metrics import compute_metrics, default_window
from app.schemas.metrics import LatencyPercentiles, MetricsResponse, MetricsWindow, TokenTotals

router = APIRouter(prefix="/v1", tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
    model: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
) -> MetricsResponse:
    """Return aggregated latency percentiles, token totals, and cost for a project."""
    if project_id is not None and project_id != project.id:
        raise GatewayHTTPException(
            status_code=403,
            message="Cannot access metrics for another project.",
            error_type="authorization_error",
            code="forbidden_project",
        )

    window_since, window_until = default_window()
    if since is not None:
        window_since = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)

    metrics = await compute_metrics(
        db,
        project.id,
        since=window_since,
        until=window_until,
        model=model,
    )

    return MetricsResponse(
        window=MetricsWindow(since=metrics.since, until=metrics.until),
        total_requests=metrics.total_requests,
        success_rate=metrics.success_rate,
        cache_hit_rate=metrics.cache_hit_rate,
        latency_ms=LatencyPercentiles(
            p50=metrics.latency_p50,
            p95=metrics.latency_p95,
            p99=metrics.latency_p99,
        ),
        tokens=TokenTotals(input=metrics.input_tokens, output=metrics.output_tokens),
        cost_usd=metrics.cost_usd,
    )
