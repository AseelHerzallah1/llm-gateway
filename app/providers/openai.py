"""OpenAI provider — chat completions via httpx (non-streaming and SSE streaming)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import CompletionRequest, CompletionResponse, LLMProvider
from app.providers.exceptions import OpenAIProviderError


class OpenAIProvider(LLMProvider):
    """Calls OpenAI's /v1/chat/completions endpoint."""

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
        payload = _build_payload(request, stream=False)

        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenAIProviderError("OpenAI request timed out", is_timeout=True) from exc
        except httpx.HTTPStatusError as exc:
            message = _extract_openai_error_message(exc.response)
            raise OpenAIProviderError(
                message,
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise OpenAIProviderError(f"OpenAI connection error: {exc}") from exc

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

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        """Forward OpenAI SSE chunks as they arrive — no full-response buffering."""
        payload = _build_payload(request, stream=True)

        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    await response.aread()
                    message = _extract_openai_error_message(response)
                    raise OpenAIProviderError(
                        message,
                        status_code=response.status_code,
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    yield f"{line}\n\n"
        except OpenAIProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise OpenAIProviderError("OpenAI request timed out", is_timeout=True) from exc
        except httpx.RequestError as exc:
            raise OpenAIProviderError(f"OpenAI connection error: {exc}") from exc

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


def _build_payload(request: CompletionRequest, *, stream: bool) -> dict:
    payload: dict = {
        "model": request.model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "stream": stream,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    return payload


def _extract_openai_error_message(response: httpx.Response) -> str:
    """Parse OpenAI error JSON when available."""
    try:
        body = response.json()
        error = body.get("error", {})
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    except Exception:
        pass
    return f"OpenAI API error (HTTP {response.status_code})"


def create_openai_provider() -> OpenAIProvider:
    """Build an OpenAI provider from application settings."""
    return OpenAIProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.openai_base_url,
    )
