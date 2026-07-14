"""OpenAI provider — non-streaming chat completions via httpx."""

from __future__ import annotations

import httpx

from app.config import settings
from app.providers.base import CompletionRequest, CompletionResponse, LLMProvider


class OpenAIProviderError(Exception):
    """Raised when the OpenAI API returns an error response."""


class OpenAIProvider(LLMProvider):
    """Calls OpenAI's /v1/chat/completions endpoint (non-streaming)."""

    def __init__(self, api_key: str, base_url: str) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")

        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    @property
    def name(self) -> str:
        return "openai"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload: dict = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenAIProviderError(
                f"OpenAI API error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise OpenAIProviderError(f"OpenAI request failed: {exc}") from exc

        data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})

        return CompletionResponse(
            id=data["id"],
            model=data["model"],
            content=choice["message"]["content"],
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            created=data["created"],
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


def create_openai_provider() -> OpenAIProvider:
    """Build an OpenAI provider from application settings."""
    return OpenAIProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.openai_base_url,
    )
