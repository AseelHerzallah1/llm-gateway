"""Persist gateway cache entries to PostgreSQL."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.cache.fingerprint import FINGERPRINT_VERSION
from app.cache.memory import GatewayCache
from app.cache.types import CacheEntry, new_cache_entry
from app.db.models.cache_entry import CacheEntryRecord
from app.db.models.request import RequestLog
from app.db.session import async_session_factory
from app.providers.base import ChatMessage

logger = logging.getLogger(__name__)


def _messages_to_json(messages: tuple[ChatMessage, ...]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _messages_from_json(raw: list | None) -> tuple[ChatMessage, ...]:
    if not raw:
        return ()
    return tuple(ChatMessage(role=item["role"], content=item["content"]) for item in raw)


def _record_to_entry(record: CacheEntryRecord) -> CacheEntry:
    return new_cache_entry(
        record.project_id,
        record.model,
        list(record.embedding),
        record.cached_response,
        entry_id=record.id,
        created_at=record.created_at,
        fingerprint=record.fingerprint,
        fingerprint_version=record.fingerprint_version,
        request_messages=_messages_from_json(record.request_messages),
        temperature=record.temperature,
        max_tokens=record.max_tokens,
        pii_values_hash=record.pii_values_hash,
    )


async def hydrate_gateway_cache(cache: GatewayCache) -> int:
    """Load all persisted cache rows into in-memory indexes."""
    async with async_session_factory() as db:
        result = await db.execute(select(CacheEntryRecord))
        records = result.scalars().all()

    for record in records:
        cache.load_entry(_record_to_entry(record))

    logger.info("Gateway cache hydrated with %d entries", len(records))
    return len(records)


async def persist_cache_entry(entry: CacheEntry) -> uuid.UUID:
    """Upsert one cache row by (project_id, fingerprint) when fingerprint is present."""
    entry_id = entry.entry_id or uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with async_session_factory() as db:
        if entry.fingerprint:
            stmt = insert(CacheEntryRecord).values(
                id=entry_id,
                project_id=entry.project_id,
                model=entry.model,
                fingerprint=entry.fingerprint,
                fingerprint_version=entry.fingerprint_version or FINGERPRINT_VERSION,
                request_messages=_messages_to_json(entry.request_messages),
                temperature=entry.temperature,
                max_tokens=entry.max_tokens,
                pii_values_hash=entry.pii_values_hash,
                embedding=entry.embedding,
                cached_response=entry.response,
                use_count=0,
                exact_use_count=0,
                semantic_use_count=0,
                created_at=entry.created_at,
                last_used_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["project_id", "fingerprint"],
                set_={
                    "model": entry.model,
                    "request_messages": _messages_to_json(entry.request_messages),
                    "temperature": entry.temperature,
                    "max_tokens": entry.max_tokens,
                    "pii_values_hash": entry.pii_values_hash,
                    "embedding": entry.embedding,
                    "cached_response": entry.response,
                    "last_used_at": now,
                },
            )
            await db.execute(stmt)
        else:
            db.add(
                CacheEntryRecord(
                    id=entry_id,
                    project_id=entry.project_id,
                    model=entry.model,
                    fingerprint=None,
                    fingerprint_version=entry.fingerprint_version,
                    request_messages=_messages_to_json(entry.request_messages),
                    temperature=entry.temperature,
                    max_tokens=entry.max_tokens,
                    pii_values_hash=entry.pii_values_hash,
                    embedding=entry.embedding,
                    cached_response=entry.response,
                    created_at=entry.created_at,
                    last_used_at=now,
                )
            )
        await db.commit()

    logger.info(
        "Cache entry persisted id=%s project_id=%s model=%s fingerprint=%s",
        entry_id,
        entry.project_id,
        entry.model,
        entry.fingerprint,
    )
    return entry_id


async def record_cache_use(entry_id: uuid.UUID, *, hit_kind: str) -> None:
    """Increment use counters for a cache hit."""
    now = datetime.now(timezone.utc)
    values: dict = {
        "use_count": CacheEntryRecord.use_count + 1,
        "last_used_at": now,
    }
    if hit_kind == "exact":
        values["exact_use_count"] = CacheEntryRecord.exact_use_count + 1
    elif hit_kind == "semantic":
        values["semantic_use_count"] = CacheEntryRecord.semantic_use_count + 1

    async with async_session_factory() as db:
        await db.execute(
            update(CacheEntryRecord).where(CacheEntryRecord.id == entry_id).values(**values)
        )
        await db.commit()


async def clear_project_benchmark_state(project_id: uuid.UUID) -> tuple[int, int]:
    """Delete cache rows and request logs for one project only (benchmark isolation)."""
    async with async_session_factory() as db:
        cache_result = await db.execute(
            delete(CacheEntryRecord).where(CacheEntryRecord.project_id == project_id)
        )
        request_result = await db.execute(
            delete(RequestLog).where(RequestLog.project_id == project_id)
        )
        await db.commit()

    cache_deleted = cache_result.rowcount or 0
    request_deleted = request_result.rowcount or 0
    logger.info(
        "Cleared benchmark state project_id=%s cache_rows=%d request_rows=%d",
        project_id,
        cache_deleted,
        request_deleted,
    )
    return cache_deleted, request_deleted


hydrate_semantic_cache = hydrate_gateway_cache
