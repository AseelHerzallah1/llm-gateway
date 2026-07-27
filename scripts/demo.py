"""Portfolio demo — walk through gateway capabilities in one script.

Usage:
    python scripts/demo.py [gateway-api-key]

Or set GATEWAY_TEST_API_KEY in .env

Requires:
    - uvicorn on http://127.0.0.1:8001
    - PostgreSQL + alembic upgrade head
    - OPENAI_API_KEY in .env
    - Seeded project (python scripts/seed_test_project.py)
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "http://127.0.0.1:8001"


def _resolve_api_key() -> str:
    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    if not api_key:
        from dotenv import load_dotenv

        load_dotenv()
        import os

        api_key = os.getenv("GATEWAY_TEST_API_KEY", "")

    if not api_key:
        print("Usage: python scripts/demo.py <gateway-api-key>")
        print("Or set GATEWAY_TEST_API_KEY in .env")
        sys.exit(1)
    return api_key


async def step_health(client: httpx.AsyncClient) -> None:
    print("\n[1/5] Health check")
    response = await client.get("/health", timeout=10.0)
    response.raise_for_status()
    data = response.json()
    print(f"  status={data.get('status')} version={data.get('version')}")


async def step_chat(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    print("\n[2/5] Non-streaming chat")
    start = time.perf_counter()
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Say hello in one word."}],
            "stream": False,
            "max_tokens": 10,
        },
        headers=headers,
        timeout=60.0,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    print(f"  reply={content!r} latency={elapsed_ms}ms")


async def step_stream(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    print("\n[3/5] Streaming chat (first few chunks)")
    saw_done = False
    event_count = 0
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Count from 1 to 3."}],
            "stream": True,
            "max_tokens": 20,
        },
        headers=headers,
        timeout=60.0,
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            event_count += 1
            if event_count <= 3:
                preview = line[:72] + ("..." if len(line) > 72 else "")
                print(f"  {preview}")
            if line.strip() == "data: [DONE]":
                saw_done = True
                break
    print(f"  events_seen={event_count} saw_done={saw_done}")


async def step_cache(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    print("\n[4/5] Semantic cache (identical prompt twice)")
    token = uuid.uuid4().hex[:8]
    prompt = f"What is 2+2? Reply with the digit only. ({token})"
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 5,
    }

    first_start = time.perf_counter()
    first = await client.post("/v1/chat/completions", json=payload, headers=headers, timeout=60.0)
    first_ms = int((time.perf_counter() - first_start) * 1000)
    first.raise_for_status()
    first_content = first.json()["choices"][0]["message"]["content"]

    second_start = time.perf_counter()
    second = await client.post("/v1/chat/completions", json=payload, headers=headers, timeout=60.0)
    second_ms = int((time.perf_counter() - second_start) * 1000)
    second.raise_for_status()
    second_content = second.json()["choices"][0]["message"]["content"]

    logs = await client.get("/v1/requests", headers=headers, params={"limit": 5}, timeout=30.0)
    logs.raise_for_status()
    recent = logs.json().get("items", [])
    cache_hits = [item.get("cache_hit") for item in recent[:2]]

    print(f"  first={first_content!r} ({first_ms}ms)")
    print(f"  second={second_content!r} ({second_ms}ms)")
    print(f"  same_content={first_content == second_content}")
    if len(cache_hits) >= 2:
        print(f"  recent_cache_hit flags (newest first): {cache_hits[0]}, {cache_hits[1]}")


async def step_metrics(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    print("\n[5/5] Metrics snapshot")
    response = await client.get("/v1/metrics", headers=headers, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    latency = data.get("latency_ms", {})
    print(f"  total_requests={data.get('total_requests')}")
    print(f"  success_rate={data.get('success_rate')}")
    print(f"  cache_hit_rate={data.get('cache_hit_rate')}")
    print(
        "  latency_ms: "
        f"p50={latency.get('p50')} p95={latency.get('p95')} p99={latency.get('p99')}"
    )
    print(f"\n  Dashboard: {BASE_URL}/dashboard")


async def main() -> None:
    api_key = _resolve_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    print("LLM Gateway demo")
    print(f"  base_url={BASE_URL}")

    try:
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            await step_health(client)
            await step_chat(client, headers)
            await step_stream(client, headers)
            await step_cache(client, headers)
            await step_metrics(client, headers)
    except httpx.ConnectError:
        print("\nERROR: Could not connect to the gateway.")
        print("Start (or restart) the server in a separate terminal:")
        print('  Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue |')
        print('    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }')
        print("  uvicorn app.main:app --host 127.0.0.1 --port 8001")
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        print(f"\nERROR: HTTP {exc.response.status_code}: {exc.response.text[:300]}")
        sys.exit(1)

    print("\nDemo complete.")


if __name__ == "__main__":
    asyncio.run(main())
