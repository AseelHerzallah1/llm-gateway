"""Persist semantic cache entries to PostgreSQL."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.cache.memory import InMemorySemanticCache
from app.cache.types import CacheEntry, new_cache_entry
from app.db.models.cache_entry import CacheEntryRecord
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)


def _record_to_entry(record: CacheEntryRecord) -> CacheEntry:
    return new_cache_entry(
        record.project_id,
        record.model,
        list(record.embedding),
        record.cached_response,
        entry_id=record.id,
        created_at=record.created_at,
    )


async def hydrate_semantic_cache(cache: InMemorySemanticCache) -> int:
    """Load all persisted cache rows into the in-memory index."""
    async with async_session_factory() as db:
        result = await db.execute(select(CacheEntryRecord))
        records = result.scalars().all()

    for record in records:
        cache.load_entry(_record_to_entry(record))

    logger.info("Semantic cache hydrated with %d entries", len(records))
    return len(records)


async def persist_cache_entry(
    project_id: uuid.UUID,
    model: str,
    embedding: list[float],
    response: str,
) -> uuid.UUID:
    """Insert one cache row and return its id."""
    entry_id = uuid.uuid4()
    async with async_session_factory() as db:
        db.add(
            CacheEntryRecord(
                id=entry_id,
                project_id=project_id,
                model=model,
                embedding=embedding,
                cached_response=response,
            )
        )
        await db.commit()

    logger.info(
        "Cache entry persisted id=%s project_id=%s model=%s",
        entry_id,
        project_id,
        model,
    )
    return entry_id


async def record_cache_use(entry_id: uuid.UUID) -> None:
    """Increment use_count and refresh last_used_at for a cache hit."""
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        await db.execute(
            update(CacheEntryRecord)
            .where(CacheEntryRecord.id == entry_id)
            .values(use_count=CacheEntryRecord.use_count + 1, last_used_at=now)
        )
        await db.commit()
