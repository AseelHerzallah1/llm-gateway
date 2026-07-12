"""Test API key authentication against the database.

Usage:
    python scripts/test_auth.py <your-api-key>
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.dependencies import resolve_project
from app.db.session import async_session_factory


async def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/test_auth.py <api-key>")
        sys.exit(1)

    api_key = sys.argv[1]

    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)

    print("Auth OK")
    print("Project ID:", project.id)
    print("Project name:", project.name)
    print("Active:", project.active)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print("Auth failed:", exc)
        sys.exit(1)
