"""Integration tests for chat route with real auth and DB logging."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.cache.chat_integration import NonStreamingCacheCheck
from app.db.models.request import RequestLog
from app.db.session import async_session_factory
from app.providers.base import CompletionResponse
from app.providers.exceptions import OpenAIProviderError


pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.mark.asyncio
async def test_chat_success_persists_request_log(db_client, monkeypatch) -> None:
    client, project, api_key = db_client

    async def fake_complete(_router, _model, _request, **kwargs):
        return CompletionResponse(
            id="chatcmpl-db-test",
            model="gpt-4o-mini",
            content="Hello",
            finish_reason="stop",
            prompt_tokens=4,
            completion_tokens=2,
            total_tokens=6,
            created=123,
        )

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(
            return_value=NonStreamingCacheCheck(cached_response=None, embedding=[1.0, 0.0])
        ),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.request_log_async", False)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )

    assert response.status_code == 200

    async with async_session_factory() as db:
        result = await db.execute(
            select(RequestLog).where(RequestLog.project_id == project.id)
        )
        row = result.scalar_one()

    assert row.status == "success"
    assert row.model == "gpt-4o-mini"
    assert row.input_tokens == 4
    assert row.output_tokens == 2


@pytest.mark.asyncio
async def test_chat_provider_error_persists_error_log(db_client, monkeypatch) -> None:
    client, project, api_key = db_client

    async def failing_complete(_router, _model, _request, **kwargs):
        raise OpenAIProviderError("upstream unavailable", status_code=503)

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(
            return_value=NonStreamingCacheCheck(cached_response=None, embedding=None)
        ),
    )
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", failing_complete)
    monkeypatch.setattr("app.config.settings.request_log_async", False)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )

    assert response.status_code == 502

    async with async_session_factory() as db:
        result = await db.execute(
            select(RequestLog).where(RequestLog.project_id == project.id)
        )
        row = result.scalar_one()

    assert row.status == "error"
    assert "upstream unavailable" in (row.error_reason or "")


@pytest.mark.asyncio
async def test_chat_async_request_log_eventually_persists(db_client, monkeypatch) -> None:
    client, project, api_key = db_client

    async def fake_complete(_router, _model, _request, **kwargs):
        return CompletionResponse(
            id="chatcmpl-async-test",
            model="gpt-4o-mini",
            content="Hello",
            finish_reason="stop",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            created=123,
        )

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(
            return_value=NonStreamingCacheCheck(cached_response=None, embedding=None)
        ),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.request_log_async", True)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert response.status_code == 200

    row = None
    for _ in range(20):
        async with async_session_factory() as db:
            result = await db.execute(
                select(RequestLog).where(RequestLog.project_id == project.id)
            )
            row = result.scalar_one_or_none()
        if row is not None:
            break
        await asyncio.sleep(0.05)

    assert row is not None
    assert row.status == "success"
