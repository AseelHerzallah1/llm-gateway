"""Integration tests for request logging persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.request import RequestLog
from app.db.session import async_session_factory
from app.observability.request_log import RequestLogCreate, persist_request_log


pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.mark.asyncio
async def test_persist_request_log_writes_row(db_project) -> None:
    project, _api_key = db_project

    await persist_request_log(
        RequestLogCreate(
            project_id=project.id,
            model="gpt-4o-mini",
            status="success",
            latency_ms=123,
            input_tokens=10,
            output_tokens=5,
        )
    )

    async with async_session_factory() as db:
        result = await db.execute(
            select(RequestLog).where(RequestLog.project_id == project.id)
        )
        row = result.scalar_one()

    assert row.status == "success"
    assert row.latency_ms == 123
    assert row.input_tokens == 10
    assert row.output_tokens == 5
    assert row.cost_usd > 0
