"""Verify semantic cache hits on repeated non-streaming prompts.

Usage:
    python scripts/test_cache_hit.py <gateway-api-key>

Requires uvicorn on http://127.0.0.1:8001 and OPENAI_API_KEY in .env.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
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
        print("Usage: python scripts/test_cache_hit.py <gateway-api-key>")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {api_key}"}
    token = uuid.uuid4().hex[:8]
    prompt = f"What is the capital of France? Reply in one word. ({token})"

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 10,
    }

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        first = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60.0,
        )
        if first.status_code != 200:
            print("First request failed:", first.status_code, first.text)
            sys.exit(1)

        first_body = first.json()
        first_content = first_body["choices"][0]["message"]["content"]

        second = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60.0,
        )
        if second.status_code != 200:
            print("Second request failed:", second.status_code, second.text)
            sys.exit(1)

        second_body = second.json()
        second_content = second_body["choices"][0]["message"]["content"]

        logs = await client.get(
            "/v1/requests",
            headers=headers,
            params={"limit": 5},
            timeout=30.0,
        )

    if second_content != first_content:
        print("Expected cached response to match first response exactly")
        print("First:", first_content)
        print("Second:", second_content)
        sys.exit(1)

    if not second_body["id"].startswith("cache-"):
        print("Expected second response id to start with cache-, got:", second_body["id"])
        sys.exit(1)

    if second_body["usage"]["total_tokens"] != 0:
        print("Expected zero token usage on cache hit")
        sys.exit(1)

    if logs.status_code != 200:
        print("Requests log failed:", logs.status_code, logs.text)
        sys.exit(1)

    recent = logs.json()["items"]
    if not recent or not recent[0].get("cache_hit"):
        print("Expected most recent request log row to have cache_hit=true")
        sys.exit(1)

    print("Cache hit OK")
    print("Response:", second_content)
    print("Second id:", second_body["id"])
    print("Logged cache_hit on latest request")


if __name__ == "__main__":
    asyncio.run(main())
