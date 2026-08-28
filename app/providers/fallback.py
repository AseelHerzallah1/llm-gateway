"""Fallback to a secondary provider when the primary fails after retries."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import replace

from app.providers.base import CompletionRequest, CompletionResponse
from app.providers.exceptions import AnthropicProviderError, OpenAIProviderError
from app.providers.retry import complete_with_retry, stream_with_retry
from app.providers.router import ProviderRouter
from app.observability.prometheus_metrics import get_prometheus_metrics

logger = logging.getLogger(__name__)


async def complete_with_fallback(
    router: ProviderRouter,
    model: str,
    request: CompletionRequest,
    *,
    max_retries: int,
    backoff_s: float,
) -> CompletionResponse:
    """Try primary provider with retries, then optional fallback provider."""
    provider = router.get_provider(model)
    try:
        return await complete_with_retry(
            provider,
            request,
            max_retries=max_retries,
            backoff_s=backoff_s,
        )
    except (OpenAIProviderError, AnthropicProviderError) as exc:
        target = router.get_fallback_target(model)
        if target is None:
            raise

        logger.warning(
            "Primary provider=%s model=%s failed; falling back to provider=%s model=%s: %s",
            provider.name,
            model,
            target.provider.name,
            target.model,
            exc.message,
        )
        get_prometheus_metrics().record_provider_fallback(
            from_provider=provider.name,
            to_provider=target.provider.name,
        )
        fallback_request = replace(request, model=target.model)
        return await complete_with_retry(
            target.provider,
            fallback_request,
            max_retries=max_retries,
            backoff_s=backoff_s,
        )


async def stream_with_fallback(
    router: ProviderRouter,
    model: str,
    request: CompletionRequest,
    *,
    max_retries: int,
    backoff_s: float,
) -> tuple[AsyncIterator[str], str | None]:
    """Try primary stream with retries, then optional fallback stream."""
    provider = router.get_provider(model)
    try:
        return await stream_with_retry(
            provider,
            request,
            max_retries=max_retries,
            backoff_s=backoff_s,
        )
    except (OpenAIProviderError, AnthropicProviderError) as exc:
        target = router.get_fallback_target(model)
        if target is None:
            raise

        logger.warning(
            "Primary stream provider=%s model=%s failed; falling back to provider=%s model=%s: %s",
            provider.name,
            model,
            target.provider.name,
            target.model,
            exc.message,
        )
        get_prometheus_metrics().record_provider_fallback(
            from_provider=provider.name,
            to_provider=target.provider.name,
        )
        fallback_request = replace(request, model=target.model)
        return await stream_with_retry(
            target.provider,
            fallback_request,
            max_retries=max_retries,
            backoff_s=backoff_s,
        )
