"""Integration tests for chat completion route."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.cache.chat_integration import NonStreamingCacheCheck
from app.providers.base import CompletionResponse


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_completion_returns_provider_response(client, monkeypatch) -> None:
    async def fake_complete(_router, _model, _request, **kwargs):
        return CompletionResponse(
            id="chatcmpl-test",
            model="gpt-4o-mini",
            content="Hello from test",
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=3,
            total_tokens=8,
            created=1234567890,
        )

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, embedding=None)),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "Hello from test"
    assert payload["usage"]["total_tokens"] == 8


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_completion_rejects_unknown_model(client) -> None:
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "unknown-model-xyz",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_redacts_pii_before_provider(client, monkeypatch) -> None:
    seen_messages: list = []

    async def fake_complete(_router, _model, request, **kwargs):
        seen_messages.extend(request.messages)
        return CompletionResponse(
            id="chatcmpl-pii",
            model="gpt-4o-mini",
            content="Acknowledged",
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=2,
            total_tokens=7,
            created=1234567890,
        )

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, embedding=None)),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Contact aseel@example.com"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert len(seen_messages) == 1
    assert seen_messages[0].content == "Contact [EMAIL_1]"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_skips_pii_when_disabled(client, monkeypatch) -> None:
    seen_messages: list = []

    async def fake_complete(_router, _model, request, **kwargs):
        seen_messages.extend(request.messages)
        return CompletionResponse(
            id="chatcmpl-no-pii",
            model="gpt-4o-mini",
            content="OK",
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=1,
            total_tokens=6,
            created=1234567890,
        )

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, embedding=None)),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", False)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Contact aseel@example.com"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert seen_messages[0].content == "Contact aseel@example.com"
