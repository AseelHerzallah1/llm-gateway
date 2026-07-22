"""Aggregate request metrics from the requests table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.request import RequestLog


@dataclass(frozen=True)
class MetricsResult:
    since: datetime
    until: datetime
    total_requests: int
    success_rate: float
    cache_hit_rate: float
    latency_p50: int
    latency_p95: int
    latency_p99: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def percentile(values: list[int], p: float) -> int:
    """Linear-interpolation percentile (p in 0–100). Returns 0 for empty input."""
    if not values:
        return 0

    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * (p / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]

    weight = rank - lower
    return int(sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * weight)


def default_window() -> tuple[datetime, datetime]:
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=24)
    return since, until


async def compute_metrics(
    db: AsyncSession,
    project_id: UUID,
    *,
    since: datetime,
    until: datetime,
    model: str | None = None,
) -> MetricsResult:
    """Load matching request logs and compute aggregated metrics."""
    filters = [
        RequestLog.project_id == project_id,
        RequestLog.created_at >= since,
        RequestLog.created_at <= until,
    ]
    if model:
        filters.append(RequestLog.model == model)

    summary = await db.execute(
        select(
            func.count(RequestLog.id),
            func.sum(RequestLog.input_tokens),
            func.sum(RequestLog.output_tokens),
            func.sum(RequestLog.cost_usd),
        ).where(*filters)
    )
    total, input_sum, output_sum, cost_sum = summary.one()

    total_requests = int(total or 0)
    if total_requests == 0:
        return MetricsResult(
            since=since,
            until=until,
            total_requests=0,
            success_rate=0.0,
            cache_hit_rate=0.0,
            latency_p50=0,
            latency_p95=0,
            latency_p99=0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )

    success_count = await db.scalar(
        select(func.count(RequestLog.id)).where(*filters, RequestLog.status == "success")
    )
    cache_hit_count = await db.scalar(
        select(func.count(RequestLog.id)).where(*filters, RequestLog.cache_hit.is_(True))
    )

    latency_rows = await db.execute(
        select(RequestLog.latency_ms).where(*filters).order_by(RequestLog.latency_ms)
    )
    latencies = [row[0] for row in latency_rows.all()]

    return MetricsResult(
        since=since,
        until=until,
        total_requests=total_requests,
        success_rate=round((success_count or 0) / total_requests, 4),
        cache_hit_rate=round((cache_hit_count or 0) / total_requests, 4),
        latency_p50=percentile(latencies, 50),
        latency_p95=percentile(latencies, 95),
        latency_p99=percentile(latencies, 99),
        input_tokens=int(input_sum or 0),
        output_tokens=int(output_sum or 0),
        cost_usd=round(float(cost_sum or 0.0), 8),
    )
