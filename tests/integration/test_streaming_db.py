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

# Manual script default is 5; pytest goes higher to stress in-process concurrency.
DEFAULT_STREAM_CONCURRENCY = 20
HIGH_STREAM_CONCURRENCY = 40


def _install_stream_router(provider: StreamingProvider) -> None:
    app.state.provider_router = RetryOnlyRouter(provider)


async def _run_streaming_request(
    client,
    api_key: str,
    request_id: int,
) -> tuple[int, bool, int]:
    saw_done = False
    status_code = 0
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
        status_code = response.status_code
        if response.status_code != 200:
            return request_id, False, status_code
        async for chunk in response.aiter_text():
            if "data: [DONE]" in chunk:
                saw_done = True
    return request_id, saw_done, status_code


async def _run_non_streaming_request(
    client,
    api_key: str,
    request_id: int,
) -> tuple[int, bool, int]:
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"ok-{request_id}"}],
            "stream": False,
        },
    )
    ok = response.status_code == 200 and "choices" in response.json()
    return request_id, ok, response.status_code


async def _assert_concurrent_stream_logs(project_id, expected_count: int) -> None:
    async with async_session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(RequestLog)
                .where(RequestLog.project_id == project_id)
            )
        ).scalar_one()
        success_count = (
            await db.execute(
                select(func.count())
                .select_from(RequestLog)
                .where(
                    RequestLog.project_id == project_id,
                    RequestLog.status == "success",
                )
            )
        ).scalar_one()

    assert count == expected_count
    assert success_count == expected_count


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
@pytest.mark.parametrize("concurrency", [DEFAULT_STREAM_CONCURRENCY, HIGH_STREAM_CONCURRENCY])
async def test_concurrent_streams_all_complete(db_client, concurrency: int) -> None:
    client, project, api_key = db_client
    provider = StreamingProvider()
    _install_stream_router(provider)

    results = await asyncio.gather(
        *(_run_streaming_request(client, api_key, i) for i in range(concurrency))
    )

    assert all(saw_done for _request_id, saw_done, _status in results)
    assert all(status == 200 for _request_id, _saw_done, status in results)
    assert provider.streams_started == concurrency

    await _assert_concurrent_stream_logs(project.id, concurrency)


@pytest.mark.asyncio
async def test_concurrent_mixed_stream_and_non_stream(db_client) -> None:
    """Mirror scripts/test_concurrent_streams.py: parallel streams plus non-stream calls."""
    client, project, api_key = db_client
    provider = StreamingProvider()
    _install_stream_router(provider)

    stream_concurrency = DEFAULT_STREAM_CONCURRENCY
    non_stream_concurrency = 3

    stream_tasks = (
        _run_streaming_request(client, api_key, i) for i in range(stream_concurrency)
    )
    non_stream_tasks = (
        _run_non_streaming_request(client, api_key, i + 100)
        for i in range(non_stream_concurrency)
    )
    results = await asyncio.gather(*stream_tasks, *non_stream_tasks)

    stream_results = results[:stream_concurrency]
    non_stream_results = results[stream_concurrency:]

    assert all(saw_done for _request_id, saw_done, _status in stream_results)
    assert all(ok for _request_id, ok, _status in non_stream_results)
    assert provider.streams_started == stream_concurrency

    expected_logs = stream_concurrency + non_stream_concurrency
    await _assert_concurrent_stream_logs(project.id, expected_logs)
