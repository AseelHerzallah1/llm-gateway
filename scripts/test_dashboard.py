"""Verify the observability dashboard page is served.

Usage:
    python scripts/test_dashboard.py

Requires uvicorn on http://127.0.0.1:8001.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        response = await client.get("/dashboard", timeout=15.0)

    if response.status_code != 200:
        print("Dashboard request failed:", response.status_code, response.text[:200])
        sys.exit(1)

    if "text/html" not in response.headers.get("content-type", ""):
        print("Expected HTML response")
        sys.exit(1)

    body = response.text
    for snippet in ("LLM Gateway", "Metrics", "Recent requests", "/v1/metrics"):
        if snippet not in body:
            print("Missing dashboard content:", snippet)
            sys.exit(1)

    print("Dashboard page OK")


if __name__ == "__main__":
    asyncio.run(main())
