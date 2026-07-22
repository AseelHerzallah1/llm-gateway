"""OpenAI embedding provider — /v1/embeddings via httpx."""

from __future__ import annotations

import httpx

from app.config import settings
from app.embeddings.base import EmbeddingProvider
from app.providers.exceptions import OpenAIProviderError


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Calls OpenAI's /v1/embeddings endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        connect_timeout: float,
        read_timeout: float,
        write_timeout: float,
        pool_timeout: float,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")

        self._model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=write_timeout,
                pool=pool_timeout,
            ),
        )

    @property
    def name(self) -> str:
        return "openai"

    async def embed(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("Cannot embed empty text")

        try:
            response = await self._client.post(
                "/embeddings",
                json={"model": self._model, "input": text},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenAIProviderError("OpenAI embedding request timed out", is_timeout=True) from exc
        except httpx.HTTPStatusError as exc:
            message = _extract_openai_error_message(exc.response)
            raise OpenAIProviderError(message, status_code=exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise OpenAIProviderError(f"OpenAI embedding connection error: {exc}") from exc

        data = response.json()
        return list(data["data"][0]["embedding"])

    async def aclose(self) -> None:
        await self._client.aclose()


def _extract_openai_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error", {})
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    except Exception:
        pass
    return f"OpenAI API error (HTTP {response.status_code})"


def create_openai_embedding_provider() -> OpenAIEmbeddingProvider:
    """Build an OpenAI embedding provider from application settings."""
    return OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.openai_base_url,
        model=settings.openai_embedding_model,
        connect_timeout=settings.openai_connect_timeout_s,
        read_timeout=settings.openai_read_timeout_s,
        write_timeout=settings.openai_write_timeout_s,
        pool_timeout=settings.openai_pool_timeout_s,
    )
