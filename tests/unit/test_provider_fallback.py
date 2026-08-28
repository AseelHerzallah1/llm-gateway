"""Unit tests for provider fallback behavior."""

from __future__ import annotations

import pytest

from app.config import settings
from app.providers.base import ChatMessage, CompletionRequest, CompletionResponse, LLMProvider
from app.providers.exceptions import OpenAIProviderError
from app.providers.fallback import complete_with_fallback
from app.providers.router import FallbackTarget, ProviderRouter


class AlwaysFailProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "groq"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        raise OpenAIProviderError("upstream unavailable", status_code=503)

    def stream(self, request: CompletionRequest):
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class SuccessProvider(LLMProvider):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        return CompletionResponse(
            id="ok",
            model=request.model,
            content=f"fallback-{request.model}",
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


class StubRouter(ProviderRouter):
    def __init__(self) -> None:
        self._primary = AlwaysFailProvider()
        self._fallback = SuccessProvider("openai")
        self._providers = {"openai": self._fallback, "groq": self._primary}

    def get_provider(self, model: str) -> LLMProvider:
        if model.startswith("llama"):
            return self._primary
        return self._fallback

    def get_fallback_target(self, model: str) -> FallbackTarget | None:
        if model.startswith("llama"):
            return FallbackTarget(self._fallback, settings.provider_fallback_openai_model)
        return None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_with_fallback_uses_secondary_provider() -> None:
    router = StubRouter()
    request = CompletionRequest(
        model="llama-3.3-70b-versatile",
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=5,
    )

    result = await complete_with_fallback(
        router,
        request.model,
        request,
        max_retries=0,
        backoff_s=0.01,
    )

    assert result.model == settings.provider_fallback_openai_model
    assert result.content == f"fallback-{settings.provider_fallback_openai_model}"
