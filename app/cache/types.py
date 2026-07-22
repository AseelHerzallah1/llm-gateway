"""In-memory semantic cache types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


@dataclass(frozen=True)
class CacheEntry:
    project_id: UUID
    model: str
    embedding: list[float]
    response: str
    created_at: datetime


@dataclass(frozen=True)
class CacheLookupResult:
    response: str
    similarity: float


def new_cache_entry(
    project_id: UUID,
    model: str,
    embedding: list[float],
    response: str,
) -> CacheEntry:
    return CacheEntry(
        project_id=project_id,
        model=model,
        embedding=embedding,
        response=response,
        created_at=datetime.now(timezone.utc),
    )
