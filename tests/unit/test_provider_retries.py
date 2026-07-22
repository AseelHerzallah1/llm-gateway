"""Unit tests for provider retry policy."""

from __future__ import annotations

import pytest

from app.providers.base import ChatMessage, CompletionRequest, CompletionResponse, LLMProvider
from app.providers.exceptions import OpenAIProviderError
from app.providers.retry import complete_with_retry, is_retryable_provider_error


class FlakyProvider(LLMProvider):
    def __init__(self, failures_before_success: int, *, retryable: bool = True) -> None:
        self._remaining_failures = failures_before_success
        self._retryable = retryable
        self.attempts = 0

    @property
    def name(self) -> str:
        return "flaky"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.attempts += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            if self._retryable:
                raise OpenAIProviderError("upstream unavailable", status_code=503)
            raise OpenAIProviderError("bad request", status_code=400)
        return CompletionResponse(
            id="test",
            model=request.model,
            content="ok",
            finish_reason="stop",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            created=0,
        )

    def stream(self, request: CompletionRequest):
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


@pytest.mark.unit
def test_retryable_detection() -> None:
    assert is_retryable_provider_error(OpenAIProviderError("rate limit", status_code=429))
    assert is_retryable_provider_error(OpenAIProviderError("timeout", is_timeout=True))
    assert is_retryable_provider_error(OpenAIProviderError("server", status_code=503))
    assert not is_retryable_provider_error(OpenAIProviderError("bad", status_code=400))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_with_retry_success() -> None:
    provider = FlakyProvider(failures_before_success=2)
    result = await complete_with_retry(
        provider,
        CompletionRequest(model="gpt-4o-mini", messages=[ChatMessage(role="user", content="hi")]),
        max_retries=3,
        backoff_s=0.01,
    )
    assert result.content == "ok"
    assert provider.attempts == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_with_retry_non_retryable() -> None:
    provider = FlakyProvider(failures_before_success=5, retryable=False)
    with pytest.raises(OpenAIProviderError) as exc_info:
        await complete_with_retry(
            provider,
            CompletionRequest(
                model="gpt-4o-mini",
                messages=[ChatMessage(role="user", content="hi")],
            ),
            max_retries=3,
            backoff_s=0.01,
        )
    assert exc_info.value.status_code == 400
    assert provider.attempts == 1
