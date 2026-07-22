"""In-memory semantic cache types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


@dataclass(frozen=True)
class CacheEntry:
    entry_id: UUID | None
    project_id: UUID
    model: str
    embedding: list[float]
    response: str
    created_at: datetime


@dataclass(frozen=True)
class CacheLookupResult:
    response: str
    similarity: float
    entry_id: UUID | None = None


def new_cache_entry(
    project_id: UUID,
    model: str,
    embedding: list[float],
    response: str,
    *,
    entry_id: UUID | None = None,
    created_at: datetime | None = None,
) -> CacheEntry:
    return CacheEntry(
        entry_id=entry_id,
        project_id=project_id,
        model=model,
        embedding=embedding,
        response=response,
        created_at=created_at or datetime.now(timezone.utc),
    )
