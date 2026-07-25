"""Test doubles for provider retry/fallback integration tests."""

from __future__ import annotations

from app.config import settings
from app.providers.base import CompletionRequest, CompletionResponse, LLMProvider
from app.providers.exceptions import OpenAIProviderError
from app.providers.router import FallbackTarget


class FlakyProvider(LLMProvider):
    """Fail N times with retryable 503, then succeed."""

    def __init__(self, failures_before_success: int) -> None:
        self._remaining_failures = failures_before_success
        self.attempts = 0

    @property
    def name(self) -> str:
        return "flaky-openai"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.attempts += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise OpenAIProviderError("upstream unavailable", status_code=503)
        return CompletionResponse(
            id="retry-success",
            model=request.model,
            content="recovered",
            finish_reason="stop",
            prompt_tokens=3,
            completion_tokens=2,
            total_tokens=5,
            created=123,
        )

    def stream(self, request: CompletionRequest):
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class AlwaysFailProvider(LLMProvider):
    def __init__(self, name: str = "always-fail") -> None:
        self._name = name
        self.attempts = 0

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.attempts += 1
        raise OpenAIProviderError("upstream unavailable", status_code=503)

    def stream(self, request: CompletionRequest):
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class SuccessProvider(LLMProvider):
    def __init__(self, name: str, *, content: str | None = None) -> None:
        self._name = name
        self._content = content
        self.attempts = 0

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.attempts += 1
        content = self._content or f"ok-{request.model}"
        return CompletionResponse(
            id="success",
            model=request.model,
            content=content,
            finish_reason="stop",
            prompt_tokens=2,
            completion_tokens=1,
            total_tokens=3,
            created=123,
        )

    def stream(self, request: CompletionRequest):
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class RetryOnlyRouter:
    """Router with one provider and no fallback."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    @property
    def provider_names(self) -> list[str]:
        return [self._provider.name]

    def get_provider(self, model: str) -> LLMProvider:
        return self._provider

    def get_fallback_target(self, model: str) -> FallbackTarget | None:
        return None

    async def aclose(self) -> None:
        await self._provider.aclose()


class GroqToOpenAiFallbackRouter:
    """Simulate Groq primary failure with OpenAI fallback."""

    def __init__(self) -> None:
        self.primary = AlwaysFailProvider(name="groq")
        self.fallback = SuccessProvider("openai")

    @property
    def provider_names(self) -> list[str]:
        return ["groq", "openai"]

    def get_provider(self, model: str) -> LLMProvider:
        if model.startswith("llama"):
            return self.primary
        return self.fallback

    def get_fallback_target(self, model: str) -> FallbackTarget | None:
        if not settings.provider_fallback_enabled:
            return None
        if model.startswith("llama"):
            return FallbackTarget(self.fallback, settings.provider_fallback_openai_model)
        return None

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.fallback.aclose()
