"""Query helpers for paginated request log listing."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.request import RequestLog

VALID_STATUS_FILTERS = frozenset({"success", "error", "cache_hit"})


def _build_filters(
    project_id: UUID,
    *,
    status: str | None,
    model: str | None,
) -> list:
    filters = [RequestLog.project_id == project_id]

    if model:
        filters.append(RequestLog.model == model)

    if status == "cache_hit":
        filters.append(RequestLog.cache_hit.is_(True))
    elif status == "success":
        filters.append(RequestLog.status == "success")
    elif status == "error":
        filters.append(RequestLog.status == "error")

    return filters


async def list_request_logs(
    db: AsyncSession,
    project_id: UUID,
    *,
    status: str | None = None,
    model: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[RequestLog]]:
    """Return total matching rows and one page of request logs (newest first)."""
    filters = _build_filters(project_id, status=status, model=model)

    total = await db.scalar(select(func.count(RequestLog.id)).where(*filters))

    result = await db.execute(
        select(RequestLog)
        .where(*filters)
        .order_by(RequestLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return int(total or 0), list(result.scalars().all())
