"""Test doubles for provider retry/fallback integration tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from app.config import settings
from app.providers.base import CompletionRequest, CompletionResponse, LLMProvider
from app.providers.exceptions import OpenAIProviderError
from app.providers.router import FallbackTarget


def sse_data(payload: dict | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload)}\n\n"


class StreamingProvider(LLMProvider):
    """Yield OpenAI-compatible SSE chunks including usage and [DONE]."""

    def __init__(self, *, name: str = "streaming-openai") -> None:
        self._name = name
        self.streams_started = 0
        self.stream_closed = False

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        text = request.messages[-1].content if request.messages else "ok"
        return CompletionResponse(
            id="stream-complete",
            model=request.model,
            content=text,
            finish_reason="stop",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            created=123,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        self.streams_started += 1
        self.stream_closed = False
        marker = request.messages[-1].content if request.messages else "chunk"
        try:
            yield sse_data({"choices": [{"delta": {"content": marker}}]})
            yield sse_data({"usage": {"prompt_tokens": 4, "completion_tokens": 6}})
            yield sse_data("[DONE]")
        finally:
            self.stream_closed = True

    async def aclose(self) -> None:
        return None


class SlowStreamProvider(StreamingProvider):
    """Stream many chunks with a small delay so clients can disconnect mid-flight."""

    def __init__(self, *, chunk_count: int = 12, delay_s: float = 0.03) -> None:
        super().__init__(name="slow-stream")
        self.chunk_count = chunk_count
        self.delay_s = delay_s

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        self.streams_started += 1
        self.stream_closed = False
        try:
            for index in range(self.chunk_count):
                await asyncio.sleep(self.delay_s)
                yield sse_data({"choices": [{"delta": {"content": str(index)}}]})
            yield sse_data({"usage": {"prompt_tokens": 2, "completion_tokens": 3}})
            yield sse_data("[DONE]")
        finally:
            self.stream_closed = True


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
