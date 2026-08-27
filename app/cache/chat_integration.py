"""Wire L1 exact + L2 verified semantic cache into non-streaming chat completions."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from fastapi import Request

from app.cache.fingerprint import (
    FINGERPRINT_VERSION,
    compute_fingerprint,
    messages_to_verifier_text,
    pii_values_hash,
)
from app.cache.persistence import persist_cache_entry, record_cache_use
from app.cache.semantic_gates import semantic_reuse_allowed
from app.cache.types import CacheHitKind, new_cache_entry
from app.config import settings
from app.db.models.project import Project
from app.embeddings.prompt import messages_to_embed_text
from app.observability.prometheus_metrics import get_prometheus_metrics
from app.observability.request_log import RequestLogCreate, persist_request_log
from app.providers.base import ChatMessage, CompletionResponse
from app.schemas.chat import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageResponse,
    Usage,
)

if TYPE_CHECKING:
    from app.cache.memory import GatewayCache
    from app.cache.verifier import AnswerEquivalenceVerifier
    from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

BYPASS_SEMANTIC_CACHE_HEADER = "x-gateway-bypass-cache"

CacheResult = Literal["exact_hit", "semantic_hit", "miss", "bypass"]


def _record_cache_operation(result: str) -> None:
    if settings.prometheus_enabled:
        get_prometheus_metrics().record_cache_operation(result)


def bypass_semantic_cache(http_request: Request) -> bool:
    """True when client asks to skip cache (e.g. latency benchmarks)."""
    value = http_request.headers.get(BYPASS_SEMANTIC_CACHE_HEADER, "").lower()
    return value in ("1", "true", "yes")


@dataclass(frozen=True)
class NonStreamingCacheCheck:
    """Result of gateway cache lookup (L1 exact and/or L2 verified semantic)."""

    cached_response: ChatCompletionResponse | None
    cache_result: CacheResult
    embedding: list[float] | None = None


def _cached_chat_response(model: str, content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=f"cache-{uuid.uuid4()}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessageResponse(content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


async def _finalize_cache_hit(
    *,
    http_request: Request,
    project: Project,
    model: str,
    content: str,
    entry_id: uuid.UUID | None,
    hit_kind: CacheHitKind,
    started_at: float,
    similarity: float | None = None,
) -> ChatCompletionResponse:
    if hit_kind == "exact":
        _record_cache_operation("exact_hit")
        cache_result: CacheResult = "exact_hit"
    else:
        _record_cache_operation("semantic_hit")
        cache_result = "semantic_hit"

    if entry_id is not None:
        try:
            await record_cache_use(entry_id, hit_kind=hit_kind)
        except Exception as exc:
            logger.warning("Failed to update cache use_count for entry_id=%s: %s", entry_id, exc)

    await persist_request_log(
        RequestLogCreate(
            project_id=project.id,
            model=model,
            status="success",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            cache_hit=True,
        )
    )

    if hit_kind == "exact":
        logger.info(
            "Exact cache hit project_id=%s model=%s entry_id=%s",
            project.id,
            model,
            entry_id,
        )
    else:
        logger.info(
            "Verified semantic cache hit project_id=%s model=%s similarity=%.4f entry_id=%s",
            project.id,
            model,
            similarity or 0.0,
            entry_id,
        )

    http_request.state.cache_result = cache_result
    return _cached_chat_response(model, content)


async def try_cached_non_streaming_completion(
    http_request: Request,
    project: Project,
    body: ChatCompletionRequest,
    messages: list[ChatMessage],
    *,
    temperature: float | None,
    max_tokens: int | None,
    token_map: dict[str, str],
    started_at: float,
) -> NonStreamingCacheCheck:
    """L1 exact lookup, then L2 candidate retrieval + verifier on miss."""
    if not settings.semantic_cache_enabled or bypass_semantic_cache(http_request):
        _record_cache_operation("lookup_skipped")
        http_request.state.cache_result = "bypass"
        return NonStreamingCacheCheck(cached_response=None, cache_result="bypass", embedding=None)

    cache: GatewayCache = http_request.app.state.semantic_cache
    fingerprint = compute_fingerprint(
        model=body.model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        token_map=token_map,
    )

    exact_entry = cache.lookup_exact(project.id, fingerprint)
    if exact_entry is not None:
        response = await _finalize_cache_hit(
            http_request=http_request,
            project=project,
            model=body.model,
            content=exact_entry.response,
            entry_id=exact_entry.entry_id,
            hit_kind="exact",
            started_at=started_at,
        )
        return NonStreamingCacheCheck(
            cached_response=response,
            cache_result="exact_hit",
            embedding=None,
        )

    if not semantic_reuse_allowed(
        messages,
        pii_redaction_enabled=settings.pii_redaction_enabled,
        token_map=token_map,
    ):
        _record_cache_operation("semantic_skipped")
        http_request.state.cache_result = "miss"
        return NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)

    if not cache.has_semantic_entries(project.id, body.model):
        _record_cache_operation("semantic_miss")
        http_request.state.cache_result = "miss"
        return NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)

    embedding_provider: EmbeddingProvider = http_request.app.state.embedding_provider
    embed_text = messages_to_embed_text(messages)

    try:
        embedding = await embedding_provider.embed(embed_text)
    except Exception as exc:
        logger.warning(
            "Embedding lookup skipped for project_id=%s: %s",
            project.id,
            exc,
        )
        _record_cache_operation("lookup_skipped")
        http_request.state.cache_result = "miss"
        return NonStreamingCacheCheck(cached_response=None, cache_result="miss", embedding=None)

    candidate = cache.lookup_semantic_candidate(
        project.id,
        body.model,
        embedding,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if candidate is None:
        _record_cache_operation("semantic_miss")
        http_request.state.cache_result = "miss"
        return NonStreamingCacheCheck(
            cached_response=None,
            cache_result="miss",
            embedding=embedding,
        )

    verifier: AnswerEquivalenceVerifier = http_request.app.state.cache_verifier
    cached_request_text = messages_to_verifier_text(list(candidate.entry.request_messages))
    new_request_text = messages_to_verifier_text(messages)

    reuse = await verifier.should_reuse(
        cached_request=cached_request_text,
        cached_response=candidate.entry.response,
        new_request=new_request_text,
    )

    if reuse is not True:
        _record_cache_operation("semantic_reject")
        http_request.state.cache_result = "miss"
        return NonStreamingCacheCheck(
            cached_response=None,
            cache_result="miss",
            embedding=embedding,
        )

    response = await _finalize_cache_hit(
        http_request=http_request,
        project=project,
        model=body.model,
        content=candidate.entry.response,
        entry_id=candidate.entry.entry_id,
        hit_kind="semantic",
        started_at=started_at,
        similarity=candidate.similarity,
    )
    return NonStreamingCacheCheck(
        cached_response=response,
        cache_result="semantic_hit",
        embedding=embedding,
    )


async def store_non_streaming_completion(
    http_request: Request,
    project: Project,
    model: str,
    messages: list[ChatMessage],
    result: CompletionResponse,
    *,
    temperature: float | None,
    max_tokens: int | None,
    token_map: dict[str, str],
    embedding: list[float] | None = None,
) -> None:
    """Store a provider completion for future L1/L2 reuse."""
    if not settings.semantic_cache_enabled or bypass_semantic_cache(http_request):
        return

    cache: GatewayCache = http_request.app.state.semantic_cache
    embedding_provider: EmbeddingProvider = http_request.app.state.embedding_provider
    embed_text = messages_to_embed_text(messages)
    fingerprint = compute_fingerprint(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        token_map=token_map,
    )
    pii_hash = pii_values_hash(token_map)

    try:
        stored_embedding = embedding
        if stored_embedding is None:
            stored_embedding = await embedding_provider.embed(embed_text)

        entry = new_cache_entry(
            project.id,
            model,
            stored_embedding,
            result.content,
            fingerprint=fingerprint,
            fingerprint_version=FINGERPRINT_VERSION,
            request_messages=tuple(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            pii_values_hash=pii_hash,
        )
        entry_id = await persist_cache_entry(entry)
        stored = new_cache_entry(
            project.id,
            model,
            stored_embedding,
            result.content,
            entry_id=entry_id,
            fingerprint=fingerprint,
            fingerprint_version=FINGERPRINT_VERSION,
            request_messages=tuple(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            pii_values_hash=pii_hash,
        )
        cache.upsert_entry(stored)
        logger.info(
            "Cache store project_id=%s model=%s entries=%d entry_id=%s fingerprint=%s",
            project.id,
            model,
            cache.size,
            entry_id,
            fingerprint,
        )
        _record_cache_operation("store")
    except Exception as exc:
        logger.warning(
            "Cache store skipped for project_id=%s: %s",
            project.id,
            exc,
        )
