"""In-memory cache types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from app.providers.base import ChatMessage

CacheHitKind = Literal["exact", "semantic"]


@dataclass(frozen=True)
class CacheEntry:
    entry_id: UUID | None
    project_id: UUID
    model: str
    embedding: list[float]
    response: str
    created_at: datetime
    fingerprint: str | None = None
    fingerprint_version: int | None = None
    request_messages: tuple[ChatMessage, ...] = ()
    temperature: float | None = None
    max_tokens: int | None = None
    pii_values_hash: str | None = None


@dataclass(frozen=True)
class SemanticCandidate:
    entry: CacheEntry
    similarity: float


@dataclass(frozen=True)
class CacheLookupResult:
    """Successful cache lookup (exact or verified semantic)."""

    response: str
    entry_id: UUID | None
    hit_kind: CacheHitKind
    similarity: float | None = None


def new_cache_entry(
    project_id: UUID,
    model: str,
    embedding: list[float],
    response: str,
    *,
    entry_id: UUID | None = None,
    created_at: datetime | None = None,
    fingerprint: str | None = None,
    fingerprint_version: int | None = None,
    request_messages: tuple[ChatMessage, ...] = (),
    temperature: float | None = None,
    max_tokens: int | None = None,
    pii_values_hash: str | None = None,
) -> CacheEntry:
    return CacheEntry(
        entry_id=entry_id,
        project_id=project_id,
        model=model,
        embedding=embedding,
        response=response,
        created_at=created_at or datetime.now(timezone.utc),
        fingerprint=fingerprint,
        fingerprint_version=fingerprint_version,
        request_messages=request_messages,
        temperature=temperature,
        max_tokens=max_tokens,
        pii_values_hash=pii_values_hash,
    )
