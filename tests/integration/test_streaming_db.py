"""E2E streaming tests: SSE delivery, client disconnect, and concurrency."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from starlette.requests import Request

from app.db.models.request import RequestLog
from app.db.session import async_session_factory
from app.main import app
from tests.fakes.providers import RetryOnlyRouter, SlowStreamProvider, StreamingProvider


pytestmark = [pytest.mark.integration, pytest.mark.db]


def _install_stream_router(provider: StreamingProvider) -> None:
    app.state.provider_router = RetryOnlyRouter(provider)


@pytest.mark.asyncio
async def test_stream_success_persists_request_log(db_client) -> None:
    client, project, api_key = db_client
    provider = StreamingProvider()
    _install_stream_router(provider)

    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "stream-ok"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        body = []
        async for chunk in response.aiter_text():
            body.append(chunk)

    text = "".join(body)
    assert "stream-ok" in text
    assert "data: [DONE]" in text
    assert provider.stream_closed is True

    async with async_session_factory() as db:
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalar_one()

    assert row.status == "success"
    assert row.input_tokens == 4
    assert row.output_tokens == 6


@pytest.mark.asyncio
async def test_stream_client_disconnect_logs_error(db_client, monkeypatch) -> None:
    client, project, api_key = db_client
    provider = SlowStreamProvider(chunk_count=20, delay_s=0.05)
    _install_stream_router(provider)

    disconnect_after_checks = 3
    check_count = 0

    original_is_disconnected = Request.is_disconnected

    async def is_disconnected(self):  # noqa: ANN001
        nonlocal check_count
        check_count += 1
        if check_count >= disconnect_after_checks:
            return True
        return await original_is_disconnected(self)

    monkeypatch.setattr("starlette.requests.Request.is_disconnected", is_disconnected)

    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "drop-me"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        async for _chunk in response.aiter_text():
            pass

    assert provider.stream_closed is True

    async with async_session_factory() as db:
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalar_one()

    assert row.status == "error"
    assert row.error_reason == "client_disconnected"


@pytest.mark.asyncio
async def test_concurrent_streams_all_complete(db_client) -> None:
    client, project, api_key = db_client
    provider = StreamingProvider()
    _install_stream_router(provider)

    async def run_one(request_id: int) -> tuple[int, bool]:
        saw_done = False
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": f"req-{request_id}"}],
                "stream": True,
            },
        ) as response:
            if response.status_code != 200:
                return request_id, False
            async for chunk in response.aiter_text():
                if "data: [DONE]" in chunk:
                    saw_done = True
        return request_id, saw_done

    results = await asyncio.gather(*(run_one(i) for i in range(5)))
    assert all(saw_done for _request_id, saw_done in results)
    assert provider.streams_started == 5

    async with async_session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(RequestLog)
                .where(RequestLog.project_id == project.id)
            )
        ).scalar_one()

    assert count == 5
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(RequestLog).where(
                    RequestLog.project_id == project.id,
                    RequestLog.status == "success",
                )
            )
        ).scalars().all()

    assert len(rows) == 5
