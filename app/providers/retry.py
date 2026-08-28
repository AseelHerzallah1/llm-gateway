"""Retry transient provider failures with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from app.observability.prometheus_metrics import get_prometheus_metrics
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
    metrics = get_prometheus_metrics()
    while True:
        started = time.perf_counter()
        status = "success"
        try:
            result = await provider.complete(request)
            return result
        except (OpenAIProviderError, AnthropicProviderError) as exc:
            status = "error"
            if attempt >= max_retries or not is_retryable_provider_error(exc):
                raise

            metrics.record_provider_retry(provider.name)
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
        finally:
            metrics.record_provider_attempt(
                provider=provider.name,
                status=status,
                duration_seconds=time.perf_counter() - started,
            )


async def stream_with_retry(
    provider: LLMProvider,
    request: CompletionRequest,
    *,
    max_retries: int,
    backoff_s: float,
) -> tuple[AsyncIterator[str], str | None]:
    """Open a provider stream and read the first chunk, retrying on transient open failures."""
    attempt = 0
    metrics = get_prometheus_metrics()
    while True:
        stream_iter = provider.stream(request)
        started = time.perf_counter()
        status = "success"
        try:
            first_chunk = await stream_iter.__anext__()
            return stream_iter, first_chunk
        except StopAsyncIteration:
            return stream_iter, None
        except (OpenAIProviderError, AnthropicProviderError) as exc:
            status = "error"
            await stream_iter.aclose()
            if attempt >= max_retries or not is_retryable_provider_error(exc):
                raise

            metrics.record_provider_retry(provider.name)
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
        finally:
            metrics.record_provider_attempt(
                provider=provider.name,
                status=status,
                duration_seconds=time.perf_counter() - started,
            )
