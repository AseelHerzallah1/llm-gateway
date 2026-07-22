"""Verify GET /v1/requests returns paginated request logs.

Usage:
    python scripts/test_requests.py <gateway-api-key>

Requires uvicorn on http://127.0.0.1:8001 and logged requests in the DB.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    if not api_key:
        from dotenv import load_dotenv

        load_dotenv()
        import os

        api_key = os.getenv("GATEWAY_TEST_API_KEY", "")

    if not api_key:
        print("Usage: python scripts/test_requests.py <gateway-api-key>")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        response = await client.get(
            "/v1/requests",
            headers=headers,
            params={"limit": 5},
            timeout=30.0,
        )

    if response.status_code != 200:
        print("Requests list failed:", response.status_code, response.text)
        sys.exit(1)

    data = response.json()
    if "total" not in data or "items" not in data:
        print("Missing total or items in response")
        sys.exit(1)

    if data["total"] < 1:
        print("Expected at least one logged request")
        sys.exit(1)

    item = data["items"][0]
    required_fields = {
        "id",
        "created_at",
        "model",
        "status",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "cache_hit",
    }
    missing = required_fields - item.keys()
    if missing:
        print("Missing item fields:", missing)
        sys.exit(1)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        filtered = await client.get(
            "/v1/requests",
            headers=headers,
            params={"status": "success", "limit": 1},
            timeout=30.0,
        )
        bad_filter = await client.get(
            "/v1/requests",
            headers=headers,
            params={"status": "not-a-status"},
            timeout=30.0,
        )

    if filtered.status_code != 200:
        print("Filtered requests failed:", filtered.status_code, filtered.text)
        sys.exit(1)

    if bad_filter.status_code != 400:
        print("Expected 400 for invalid status filter, got:", bad_filter.status_code)
        sys.exit(1)

    print("Requests endpoint OK")
    print("Total:", data["total"])
    print("First item:", item)


if __name__ == "__main__":
    asyncio.run(main())
