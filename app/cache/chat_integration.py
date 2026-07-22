"""Wire semantic cache into non-streaming chat completions."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request

from app.cache.persistence import persist_cache_entry, record_cache_use
from app.config import settings
from app.db.models.project import Project
from app.embeddings.prompt import messages_to_embed_text
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
    from app.cache.memory import InMemorySemanticCache
    from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NonStreamingCacheCheck:
    """Result of a semantic cache lookup attempt."""

    cached_response: ChatCompletionResponse | None
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


async def try_cached_non_streaming_completion(
    http_request: Request,
    project: Project,
    body: ChatCompletionRequest,
    messages: list[ChatMessage],
    started_at: float,
    latency_ms: int,
) -> NonStreamingCacheCheck:
    """Return a cached completion on semantic cache hit, or embedding for reuse on miss."""
    if not settings.semantic_cache_enabled:
        return NonStreamingCacheCheck(cached_response=None, embedding=None)

    cache: InMemorySemanticCache = http_request.app.state.semantic_cache
    if not cache.has_entries(project.id, body.model):
        return NonStreamingCacheCheck(cached_response=None, embedding=None)

    embedding_provider: EmbeddingProvider = http_request.app.state.embedding_provider
    embed_text = messages_to_embed_text(messages)

    try:
        embedding = await embedding_provider.embed(embed_text)
        hit = cache.lookup(project.id, body.model, embedding)
    except Exception as exc:
        logger.warning(
            "Semantic cache lookup skipped for project_id=%s: %s",
            project.id,
            exc,
        )
        return NonStreamingCacheCheck(cached_response=None, embedding=None)

    if hit is None:
        return NonStreamingCacheCheck(cached_response=None, embedding=embedding)

    logger.info(
        "Semantic cache hit project_id=%s model=%s similarity=%.4f entry_id=%s",
        project.id,
        body.model,
        hit.similarity,
        hit.entry_id,
    )

    if hit.entry_id is not None:
        try:
            await record_cache_use(hit.entry_id)
        except Exception as exc:
            logger.warning(
                "Failed to update cache use_count for entry_id=%s: %s",
                hit.entry_id,
                exc,
            )

    await persist_request_log(
        RequestLogCreate(
            project_id=project.id,
            model=body.model,
            status="success",
            latency_ms=latency_ms,
            cache_hit=True,
        )
    )

    return NonStreamingCacheCheck(
        cached_response=_cached_chat_response(body.model, hit.response),
        embedding=embedding,
    )


async def store_non_streaming_completion(
    http_request: Request,
    project: Project,
    model: str,
    messages: list[ChatMessage],
    result: CompletionResponse,
    *,
    embedding: list[float] | None = None,
) -> None:
    """Store a provider completion in the semantic cache."""
    if not settings.semantic_cache_enabled:
        return

    cache: InMemorySemanticCache = http_request.app.state.semantic_cache
    embedding_provider: EmbeddingProvider = http_request.app.state.embedding_provider
    embed_text = messages_to_embed_text(messages)

    try:
        stored_embedding = embedding
        if stored_embedding is None:
            stored_embedding = await embedding_provider.embed(embed_text)

        entry_id = await persist_cache_entry(
            project.id,
            model,
            stored_embedding,
            result.content,
        )
        cache.store(
            project.id,
            model,
            stored_embedding,
            result.content,
            entry_id=entry_id,
        )
        logger.info(
            "Semantic cache store project_id=%s model=%s entries=%d entry_id=%s",
            project.id,
            model,
            cache.size,
            entry_id,
        )
    except Exception as exc:
        logger.warning(
            "Semantic cache store skipped for project_id=%s: %s",
            project.id,
            exc,
        )
