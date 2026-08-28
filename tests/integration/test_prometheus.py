"""Integration tests for GET /metrics Prometheus exposition."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from prometheus_client import generate_latest

from app.cache.chat_integration import NonStreamingCacheCheck
from app.config import settings
from app.main import app
from app.observability.prometheus_metrics import get_prometheus_metrics
from app.providers.base import CompletionResponse
from tests.fakes.providers import FlakyProvider, GroqToOpenAiFallbackRouter, RetryOnlyRouter, StreamingProvider

pytestmark = [pytest.mark.integration]


def _patch_non_stream_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(
            return_value=NonStreamingCacheCheck(
                cached_response=None,
                cache_result="miss",
                embedding=None,
            )
        ),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.config.settings.request_log_async", False)


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format(client, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.prometheus_enabled", True)

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "llmgateway_requests_total" in body
    assert "# HELP llmgateway_requests_total" in body


@pytest.mark.asyncio
async def test_metrics_disabled_returns_404(client, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.prometheus_enabled", False)

    response = await client.get("/metrics")

    assert response.status_code == 404
    assert "disabled" in response.text.lower()


@pytest.mark.asyncio
async def test_chat_increments_gateway_request_metrics(client, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.prometheus_enabled", True)
    _patch_non_stream_cache(monkeypatch)

    async def fake_complete(_router, _model, _request, **kwargs):
        return CompletionResponse(
            id="ok",
            model="gpt-4o-mini",
            content="hello",
            finish_reason="stop",
            prompt_tokens=4,
            completion_tokens=2,
            total_tokens=6,
            created=1,
        )

    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200

    payload = generate_latest(get_prometheus_metrics().registry).decode()
    assert 'llmgateway_requests_total{cache_result="miss",status="success",stream="false"} 1.0' in payload
    assert 'llmgateway_tokens_total{direction="input"} 4.0' in payload
    assert 'llmgateway_tokens_total{direction="output"} 2.0' in payload


@pytest.mark.asyncio
async def test_streaming_request_labels(client, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.prometheus_enabled", True)
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.config.settings.request_log_async", False)

    provider = StreamingProvider()
    app.state.provider_router = RetryOnlyRouter(provider)

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "stream-me"}],
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert "data:" in response.text

    payload = generate_latest(get_prometheus_metrics().registry).decode()
    assert 'llmgateway_requests_total{cache_result="none",status="success",stream="true"} 1.0' in payload


@pytest.mark.db
@pytest.mark.asyncio
async def test_provider_retry_metrics(db_client, monkeypatch) -> None:
    client, _, api_key = db_client
    monkeypatch.setattr("app.config.settings.prometheus_enabled", True)
    monkeypatch.setattr("app.config.settings.provider_max_retries", 2)
    monkeypatch.setattr("app.config.settings.provider_retry_backoff_s", 0.01)
    _patch_non_stream_cache(monkeypatch)

    flaky = FlakyProvider(failures_before_success=1)
    app.state.provider_router = RetryOnlyRouter(flaky)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200

    payload = generate_latest(get_prometheus_metrics().registry).decode()
    assert 'llmgateway_provider_retries_total{provider="openai"} 1.0' in payload
    assert 'llmgateway_provider_requests_total{provider="openai",status="error"} 1.0' in payload
    assert 'llmgateway_provider_requests_total{provider="openai",status="success"} 1.0' in payload


@pytest.mark.db
@pytest.mark.asyncio
async def test_provider_fallback_metrics(db_client, monkeypatch) -> None:
    client, _, api_key = db_client
    monkeypatch.setattr("app.config.settings.prometheus_enabled", True)
    monkeypatch.setattr("app.config.settings.provider_fallback_enabled", True)
    _patch_non_stream_cache(monkeypatch)

    app.state.provider_router = GroqToOpenAiFallbackRouter()

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200

    payload = generate_latest(get_prometheus_metrics().registry).decode()
    assert (
        'llmgateway_provider_fallbacks_total{from_provider="groq",to_provider="openai"} 1.0'
        in payload
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_cache_operation_metrics(db_cache_client, monkeypatch) -> None:
    client, _, api_key, cache, provider, embedding_provider, verifier = db_cache_client
    monkeypatch.setattr("app.config.settings.prometheus_enabled", True)

    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "cache metrics exact hit test"}],
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    first = await client.post("/v1/chat/completions", headers=headers, json=body)
    assert first.status_code == 200
    assert provider.attempts == 1

    second = await client.post("/v1/chat/completions", headers=headers, json=body)
    assert second.status_code == 200
    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 1
    assert len(verifier.calls) == 0

    payload = generate_latest(get_prometheus_metrics().registry).decode()
    assert 'llmgateway_cache_operations_total{result="exact_hit"} 1.0' in payload
    assert 'llmgateway_cache_operations_total{result="store"} 1.0' in payload
    assert 'llmgateway_requests_total{cache_result="exact_hit",status="success",stream="false"} 1.0' in payload
