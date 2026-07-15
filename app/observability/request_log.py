"""Persist per-request observability records to the database."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from app.db.models.request import RequestLog
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestLogCreate:
    """Fields required to insert one request log row."""

    project_id: UUID
    model: str
    status: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cache_hit: bool = False
    error_reason: str | None = None


async def persist_request_log(data: RequestLogCreate) -> None:
    """Write one request log row. Uses its own DB session (safe for streaming)."""
    async with async_session_factory() as db:
        db.add(
            RequestLog(
                project_id=data.project_id,
                model=data.model,
                status=data.status,
                latency_ms=data.latency_ms,
                input_tokens=data.input_tokens,
                output_tokens=data.output_tokens,
                cost_usd=data.cost_usd,
                cache_hit=data.cache_hit,
                error_reason=data.error_reason,
            )
        )
        await db.commit()

    logger.info(
        "Request logged project_id=%s model=%s status=%s latency_ms=%d tokens=%d/%d",
        data.project_id,
        data.model,
        data.status,
        data.latency_ms,
        data.input_tokens,
        data.output_tokens,
    )
