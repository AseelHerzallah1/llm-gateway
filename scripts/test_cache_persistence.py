"""Verify cache_entries persistence and hydration (offline DB).

Usage:
    python scripts/test_cache_persistence.py

Requires PostgreSQL and migration 0003 applied.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.memory import InMemorySemanticCache
from app.cache.persistence import hydrate_semantic_cache, persist_cache_entry, record_cache_use
from app.db.models.cache_entry import CacheEntryRecord
from app.db.models.project import Project
from app.db.session import async_session_factory


async def main() -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Project).limit(1))
        project = result.scalar_one_or_none()

    if project is None:
        print("No project in database — run seed_test_project.py first")
        sys.exit(1)

    project_id = project.id
    model = "gpt-4o-mini"
    embedding = [1.0, 0.0, 0.0]
    response = "Paris is the capital of France."

    entry_id = await persist_cache_entry(project_id, model, embedding, response)

    cache = InMemorySemanticCache(similarity_threshold=0.92)
    loaded = await hydrate_semantic_cache(cache)
    if loaded < 1:
        print("Expected at least one hydrated cache entry")
        sys.exit(1)

    hit = cache.lookup(project_id, model, [0.995, 0.05, 0.0])
    if hit is None or hit.response != response:
        print("Expected hydrated cache lookup to hit")
        sys.exit(1)

    await record_cache_use(entry_id)

    async with async_session_factory() as db:
        result = await db.execute(
            select(CacheEntryRecord.use_count).where(CacheEntryRecord.id == entry_id)
        )
        use_count = result.scalar_one()

        remaining = await db.execute(select(func.count(CacheEntryRecord.id)))
        total_rows = remaining.scalar_one()

    if use_count != 1:
        print("Expected use_count=1 after cache hit, got", use_count)
        sys.exit(1)

    print("Cache persistence OK")
    print("Entry id:", entry_id)
    print("Total cache rows in DB:", total_rows)


if __name__ == "__main__":
    asyncio.run(main())
