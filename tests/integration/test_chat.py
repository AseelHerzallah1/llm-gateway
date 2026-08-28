"""Integration tests for chat completion route."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.cache.chat_integration import NonStreamingCacheCheck
from app.providers.base import CompletionResponse
from app.schemas.chat import ChatChoice, ChatCompletionResponse, ChatMessageResponse, Usage


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
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)),
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
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)),
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
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)),
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


VISA_TEST_CARD = "4111 1111 1111 1111"
GB_IBAN = "GB82 WEST 1234 5698 7654 32"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_redacts_credit_card_before_provider(client, monkeypatch) -> None:
    seen_messages: list = []

    async def fake_complete(_router, _model, request, **kwargs):
        seen_messages.extend(request.messages)
        return CompletionResponse(
            id="chatcmpl-card",
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
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)
    monkeypatch.setattr("app.config.settings.pii_redact_credit_card", True)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"Charge {VISA_TEST_CARD}"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert seen_messages[0].content == "Charge [CREDIT_CARD_1]"
    assert VISA_TEST_CARD not in seen_messages[0].content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_detokenizes_credit_card_in_response(client, monkeypatch) -> None:
    async def fake_complete(_router, _model, request, **kwargs):
        return CompletionResponse(
            id="chatcmpl-card-detok",
            model="gpt-4o-mini",
            content="Card on file: [CREDIT_CARD_1]",
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=4,
            total_tokens=9,
            created=1234567890,
        )

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)
    monkeypatch.setattr("app.config.settings.pii_redact_credit_card", True)
    monkeypatch.setattr("app.config.settings.pii_detokenize_responses", True)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"Card {VISA_TEST_CARD}"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == f"Card on file: {VISA_TEST_CARD}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_redacts_iban_before_provider(client, monkeypatch) -> None:
    seen_messages: list = []

    async def fake_complete(_router, _model, request, **kwargs):
        seen_messages.extend(request.messages)
        return CompletionResponse(
            id="chatcmpl-iban",
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
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)
    monkeypatch.setattr("app.config.settings.pii_redact_iban", True)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"Wire to {GB_IBAN}"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert seen_messages[0].content == "Wire to [IBAN_1]"
    assert GB_IBAN not in seen_messages[0].content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_redacted_prompt_reaches_cache_and_store(client, monkeypatch) -> None:
    cache_messages: list = []
    stored_messages: list = []

    async def fake_cache(_http_request, _project, _body, messages, *_args, **_kwargs):
        cache_messages.extend(messages)
        return NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)

    async def fake_store(_request, _project, _model, messages, *_args, **_kwargs):
        stored_messages.extend(messages)

    async def fake_complete(_router, _model, request, **kwargs):
        return CompletionResponse(
            id="chatcmpl-cache-pii",
            model="gpt-4o-mini",
            content="OK",
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=1,
            total_tokens=6,
            created=1234567890,
        )

    monkeypatch.setattr("app.routes.chat.try_cached_non_streaming_completion", fake_cache)
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", fake_store)
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)

    raw_email = "aseel@example.com"
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"Contact {raw_email}"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert len(cache_messages) == 1
    assert cache_messages[0].content == "Contact [EMAIL_1]"
    assert raw_email not in cache_messages[0].content
    assert len(stored_messages) == 1
    assert stored_messages[0].content == "Contact [EMAIL_1]"
    assert raw_email not in stored_messages[0].content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_detokenizes_cached_response_on_cache_hit(client, monkeypatch) -> None:
    raw_email = "aseel@example.com"
    cached_response = ChatCompletionResponse(
        id="cache-detok",
        created=1234567890,
        model="gpt-4o-mini",
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessageResponse(content=f"Please write to [EMAIL_1] today."),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(
            return_value=NonStreamingCacheCheck(
                cached_response=cached_response,
                cache_result="exact_hit",
                embedding=None,
            )
        ),
    )
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", AsyncMock())
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)
    monkeypatch.setattr("app.config.settings.pii_detokenize_responses", True)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"Contact {raw_email}"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["choices"][0]["message"]["content"]
        == f"Please write to {raw_email} today."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_leaves_tokens_when_detokenize_disabled(client, monkeypatch) -> None:
    raw_email = "aseel@example.com"

    async def fake_complete(_router, _model, request, **kwargs):
        return CompletionResponse(
            id="chatcmpl-no-detok",
            model="gpt-4o-mini",
            content="Please write to [EMAIL_1] today.",
            finish_reason="stop",
            prompt_tokens=5,
            completion_tokens=4,
            total_tokens=9,
            created=1234567890,
        )

    monkeypatch.setattr(
        "app.routes.chat.try_cached_non_streaming_completion",
        AsyncMock(return_value=NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)),
    )
    monkeypatch.setattr("app.routes.chat.store_non_streaming_completion", AsyncMock())
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.routes.chat.complete_with_fallback", fake_complete)
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)
    monkeypatch.setattr("app.config.settings.pii_detokenize_responses", False)

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"Contact {raw_email}"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Please write to [EMAIL_1] today."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_streaming_bypasses_pii_redaction(client, monkeypatch) -> None:
    """Documents intentional limitation: streaming sends raw prompt to provider."""
    raw_email = "aseel@example.com"
    seen_messages: list = []

    async def fake_stream(_router, _model, request, **kwargs):
        seen_messages.extend(request.messages)

        async def stream_events():
            yield 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            yield "data: [DONE]\n\n"

        return stream_events(), None

    monkeypatch.setattr("app.routes.chat.stream_with_fallback", fake_stream)
    monkeypatch.setattr("app.routes.chat.persist_request_log", AsyncMock())
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)

    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw-sk-test-key"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": f"Contact {raw_email}"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        async for _chunk in response.aiter_text():
            pass

    assert len(seen_messages) == 1
    assert seen_messages[0].content == f"Contact {raw_email}"
    assert "[EMAIL_1]" not in seen_messages[0].content
