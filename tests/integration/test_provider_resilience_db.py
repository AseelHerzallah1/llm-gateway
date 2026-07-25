"""E2E resilience tests: retry and fallback through chat + real DB logging."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.cache.chat_integration import NonStreamingCacheCheck
from app.config import settings
from app.db.models.request import RequestLog
from app.db.session import async_session_factory
from app.main import app
from tests.fakes.providers import FlakyProvider, GroqToOpenAiFallbackRouter, RetryOnlyRouter


pytestmark = [pytest.mark.integration, pytest.mark.db]


def _patch_chat_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(
            return_value=NonStreamingCacheCheck(cached_response=None, embedding=None)
        ),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.config.settings.request_log_async", False)
    monkeypatch.setattr("app.config.settings.provider_max_retries", 2)
    monkeypatch.setattr("app.config.settings.provider_retry_backoff_s", 0.01)
    monkeypatch.setattr("app.config.settings.provider_fallback_enabled", True)


@pytest.mark.asyncio
async def test_chat_retries_transient_provider_error(db_client, monkeypatch) -> None:
    client, project, api_key = db_client
    flaky = FlakyProvider(failures_before_success=2)
    app.state.provider_router = RetryOnlyRouter(flaky)
    _patch_chat_dependencies(monkeypatch)

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
    assert response.json()["choices"][0]["message"]["content"] == "recovered"
    assert flaky.attempts == 3

    async with async_session_factory() as db:
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalar_one()

    assert row.status == "success"
    assert row.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_chat_falls_back_to_secondary_provider(db_client, monkeypatch) -> None:
    client, project, api_key = db_client
    router = GroqToOpenAiFallbackRouter()
    app.state.provider_router = router
    _patch_chat_dependencies(monkeypatch)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == settings.provider_fallback_openai_model
    assert router.primary.attempts == 3
    assert router.fallback.attempts == 1

    async with async_session_factory() as db:
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalar_one()

    assert row.status == "success"
    assert row.model == settings.provider_fallback_openai_model


@pytest.mark.asyncio
async def test_chat_fails_when_primary_and_fallback_exhausted(db_client, monkeypatch) -> None:
    client, project, api_key = db_client
    router = GroqToOpenAiFallbackRouter()
    router.fallback = router.primary  # both sides always fail
    app.state.provider_router = router
    _patch_chat_dependencies(monkeypatch)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )

    assert response.status_code == 502

    async with async_session_factory() as db:
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalar_one()

    assert row.status == "error"
