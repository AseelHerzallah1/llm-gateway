"""Verify request logging to the requests table.

Usage:
    python scripts/test_request_logging.py <gateway-api-key>

Requires uvicorn on http://127.0.0.1:8001 and migration 0002 applied.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.dependencies import resolve_project
from app.db.models.request import RequestLog
from app.db.session import async_session_factory


async def main() -> None:
    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    if not api_key:
        from dotenv import load_dotenv

        load_dotenv()
        import os

        api_key = os.getenv("GATEWAY_TEST_API_KEY", "")

    if not api_key:
        print("Usage: python scripts/test_request_logging.py <gateway-api-key>")
        sys.exit(1)

    async with async_session_factory() as db:
        project = await resolve_project(db, api_key)

    async with async_session_factory() as db:
        before = await db.execute(
            select(RequestLog).where(RequestLog.project_id == project.id)
        )
        count_before = len(before.scalars().all())

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Say hi in one word."}],
        "stream": False,
        "max_tokens": 5,
    }

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        response = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    if response.status_code != 200:
        print("Chat request failed:", response.status_code, response.text)
        sys.exit(1)

    async with async_session_factory() as db:
        result = await db.execute(
            select(RequestLog)
            .where(RequestLog.project_id == project.id)
            .order_by(RequestLog.created_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()

    if latest is None:
        print("No request log row found")
        sys.exit(1)

    print("Request logging OK")
    print("Status:", latest.status)
    print("Model:", latest.model)
    print("Latency ms:", latest.latency_ms)
    print("Input tokens:", latest.input_tokens)
    print("Output tokens:", latest.output_tokens)
    print("Cost USD:", latest.cost_usd)

    if latest.status == "success" and latest.cost_usd <= 0:
        print("Expected cost_usd > 0 for successful request with tokens")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
