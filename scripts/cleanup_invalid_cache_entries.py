"""Remove cache rows with invalid embedding dimensions (e.g. pytest 3D vectors).

Usage:
    python scripts/cleanup_invalid_cache_entries.py

Requires PostgreSQL. Restart uvicorn after running so hydration reloads clean data.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models.cache_entry import CacheEntryRecord
from app.db.session import async_session_factory

# text-embedding-3-small
EXPECTED_DIMENSIONS = 1536


async def main() -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(CacheEntryRecord))
        records = result.scalars().all()
        invalid_ids = [row.id for row in records if len(row.embedding) != EXPECTED_DIMENSIONS]

        if not invalid_ids:
            print(f"No invalid cache entries found ({len(records)} total rows).")
            return

        await db.execute(delete(CacheEntryRecord).where(CacheEntryRecord.id.in_(invalid_ids)))
        await db.commit()

    print(f"Removed {len(invalid_ids)} invalid cache row(s) (was {len(records)} total).")
    print("Restart uvicorn, then re-run: python scripts/test_cache_hit.py")


if __name__ == "__main__":
    asyncio.run(main())
