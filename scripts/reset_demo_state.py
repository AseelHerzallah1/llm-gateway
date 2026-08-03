"""Reset semantic cache and request logs for a clean portfolio demo.

Usage:
    python scripts/reset_demo_state.py

Clears cache_entries and requests tables, then reloads in-memory cache on next
uvicorn restart (or restart uvicorn now for immediate effect).

Does not delete projects or API keys.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models.cache_entry import CacheEntryRecord
from app.db.models.request import RequestLog
from app.db.session import async_session_factory


async def main() -> None:
    async with async_session_factory() as db:
        cache_count = await db.scalar(select(func.count()).select_from(CacheEntryRecord)) or 0
        request_count = await db.scalar(select(func.count()).select_from(RequestLog)) or 0

        await db.execute(delete(CacheEntryRecord))
        await db.execute(delete(RequestLog))
        await db.commit()

    print(f"Cleared {cache_count} cache_entries row(s) and {request_count} requests row(s).")
    print("Restart uvicorn so the in-memory cache reloads empty:")
    print(
        "  Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue | "
        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
    )
    print("  uvicorn app.main:app --host 127.0.0.1 --port 8001")


if __name__ == "__main__":
    asyncio.run(main())
