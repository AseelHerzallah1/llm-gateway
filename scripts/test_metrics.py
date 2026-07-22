"""Verify GET /v1/metrics aggregates request logs.

Usage:
    python scripts/test_metrics.py <gateway-api-key>

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
        print("Usage: python scripts/test_metrics.py <gateway-api-key>")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        response = await client.get("/v1/metrics", headers=headers, timeout=30.0)

    if response.status_code != 200:
        print("Metrics request failed:", response.status_code, response.text)
        sys.exit(1)

    data = response.json()
    required = {
        "window",
        "total_requests",
        "success_rate",
        "cache_hit_rate",
        "latency_ms",
        "tokens",
        "cost_usd",
    }
    missing = required - data.keys()
    if missing:
        print("Missing fields:", missing)
        sys.exit(1)

    latency = data["latency_ms"]
    for key in ("p50", "p95", "p99"):
        if key not in latency:
            print(f"Missing latency_ms.{key}")
            sys.exit(1)

    print("Metrics endpoint OK")
    print("Total requests:", data["total_requests"])
    print("Success rate:", data["success_rate"])
    print("Latency ms:", latency)
    print("Tokens:", data["tokens"])
    print("Cost USD:", data["cost_usd"])


if __name__ == "__main__":
    asyncio.run(main())
