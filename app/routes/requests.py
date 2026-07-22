"""Request log routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_project
from app.db.models.project import Project
from app.db.session import get_db
from app.errors import invalid_request_error
from app.observability.request_list import VALID_STATUS_FILTERS, list_request_logs
from app.schemas.requests import RequestListResponse, RequestLogItem

router = APIRouter(prefix="/v1", tags=["requests"])


@router.get("/requests", response_model=RequestListResponse)
async def get_requests(
    project: Annotated[Project, Depends(get_current_project)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Annotated[str | None, Query()] = None,
    model: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RequestListResponse:
    """Return a paginated list of request logs for the authenticated project."""
    if status is not None and status not in VALID_STATUS_FILTERS:
        raise invalid_request_error(
            f"Invalid status filter '{status}'. Allowed: success, error, cache_hit."
        )

    total, rows = await list_request_logs(
        db,
        project.id,
        status=status,
        model=model,
        limit=limit,
        offset=offset,
    )

    items = [
        RequestLogItem(
            id=row.id,
            created_at=row.created_at,
            model=row.model,
            status=row.status,
            latency_ms=row.latency_ms,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cost_usd=row.cost_usd,
            cache_hit=row.cache_hit,
        )
        for row in rows
    ]

    return RequestListResponse(total=total, items=items)
