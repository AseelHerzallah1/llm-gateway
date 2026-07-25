"""Retry transient provider failures with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.providers.base import CompletionRequest, CompletionResponse, LLMProvider
from app.providers.exceptions import AnthropicProviderError, OpenAIProviderError

logger = logging.getLogger(__name__)

ProviderError = OpenAIProviderError | AnthropicProviderError


def is_retryable_provider_error(exc: ProviderError) -> bool:
    """Return True for timeouts and transient upstream failures."""
    if exc.is_timeout:
        return True

    status = exc.status_code
    if status == 429:
        return True
    if status is not None and status >= 500:
        return True

    return False


async def complete_with_retry(
    provider: LLMProvider,
    request: CompletionRequest,
    *,
    max_retries: int,
    backoff_s: float,
) -> CompletionResponse:
    """Call provider.complete with retries on transient errors."""
    attempt = 0
    while True:
        try:
            return await provider.complete(request)
        except (OpenAIProviderError, AnthropicProviderError) as exc:
            if attempt >= max_retries or not is_retryable_provider_error(exc):
                raise

            delay = backoff_s * (2**attempt)
            logger.warning(
                "Retrying provider=%s attempt=%d/%d after %.2fs: %s",
                provider.name,
                attempt + 1,
                max_retries,
                delay,
                exc.message,
            )
            await asyncio.sleep(delay)
            attempt += 1


async def stream_with_retry(
    provider: LLMProvider,
    request: CompletionRequest,
    *,
    max_retries: int,
    backoff_s: float,
) -> tuple[AsyncIterator[str], str | None]:
    """Open a provider stream and read the first chunk, retrying on transient open failures."""
    attempt = 0
    while True:
        stream_iter = provider.   stream(request)
        try:
            first_chunk = await stream_iter.__anext__()
            return stream_iter, first_chunk
        except StopAsyncIteration:
            return stream_iter, None
        except (OpenAIProviderError, AnthropicProviderError) as exc:
            await stream_iter.aclose()
            if attempt >= max_retries or not is_retryable_provider_error(exc):
                raise

            delay = backoff_s * (2**attempt)
            logger.warning(
                "Retrying provider=%s stream attempt=%d/%d after %.2fs: %s",
                provider.name,
                attempt + 1,
                max_retries,
                delay,
                exc.message,
            )
            await asyncio.sleep(delay)
            attempt += 1
