"""Verify concurrent streaming requests through the gateway.

Fires multiple parallel stream=true requests and checks they all complete
without interfering with each other.

Usage:
    python scripts/test_concurrent_streams.py <gateway-api-key> [concurrency]

Or set GATEWAY_TEST_API_KEY in .env

Requires uvicorn on http://127.0.0.1:8001 and OPENAI_API_KEY configured.
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "http://127.0.0.1:8001"
DEFAULT_CONCURRENCY = 5


@dataclass
class StreamResult:
    request_id: int
    ok: bool
    status_code: int
    saw_done: bool
    event_count: int
    elapsed_s: float
    error: str | None = None


async def run_streaming_request(
    client: httpx.AsyncClient,
    api_key: str,
    request_id: int,
) -> StreamResult:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": f"Reply with only the digit {request_id}. Nothing else.",
            }
        ],
        "stream": True,
        "max_tokens": 5,
    }
    start = time.perf_counter()
    saw_done = False
    event_count = 0
    status_code = 0

    try:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        ) as response:
            status_code = response.status_code
            if response.status_code != 200:
                body = await response.aread()
                return StreamResult(
                    request_id=request_id,
                    ok=False,
                    status_code=status_code,
                    saw_done=False,
                    event_count=0,
                    elapsed_s=time.perf_counter() - start,
                    error=body.decode("utf-8", errors="replace")[:200],
                )

            async for line in response.aiter_lines():
                if not line:
                    continue
                event_count += 1
                if line.strip() == "data: [DONE]":
                    saw_done = True
    except Exception as exc:
        return StreamResult(
            request_id=request_id,
            ok=False,
            status_code=status_code,
            saw_done=saw_done,
            event_count=event_count,
            elapsed_s=time.perf_counter() - start,
            error=str(exc),
        )

    elapsed = time.perf_counter() - start
    return StreamResult(
        request_id=request_id,
        ok=saw_done,
        status_code=status_code,
        saw_done=saw_done,
        event_count=event_count,
        elapsed_s=elapsed,
    )


async def run_non_streaming_request(
    client: httpx.AsyncClient,
    api_key: str,
    request_id: int,
) -> StreamResult:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": f"Reply with only the word 'ok-{request_id}'.",
            }
        ],
        "stream": False,
        "max_tokens": 5,
    }
    start = time.perf_counter()

    try:
        response = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
    except Exception as exc:
        return StreamResult(
            request_id=request_id,
            ok=False,
            status_code=0,
            saw_done=False,
            event_count=0,
            elapsed_s=time.perf_counter() - start,
            error=str(exc),
        )

    elapsed = time.perf_counter() - start
    ok = response.status_code == 200 and "choices" in response.json()
    return StreamResult(
        request_id=request_id,
        ok=ok,
        status_code=response.status_code,
        saw_done=ok,
        event_count=1 if ok else 0,
        elapsed_s=elapsed,
        error=None if ok else response.text[:200],
    )


def _resolve_api_key() -> str:
    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    if not api_key:
        from dotenv import load_dotenv

        load_dotenv()
        import os

        api_key = os.getenv("GATEWAY_TEST_API_KEY", "")

    if not api_key:
        print("Usage: python scripts/test_concurrent_streams.py <gateway-api-key> [concurrency]")
        sys.exit(1)
    return api_key


async def main() -> None:
    api_key = _resolve_api_key()
    concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CONCURRENCY

    print(f"Running {concurrency} concurrent streaming requests...")
    wall_start = time.perf_counter()

    limits = httpx.Limits(max_connections=concurrency + 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=BASE_URL, limits=limits) as client:
        stream_results = await asyncio.gather(
            *[run_streaming_request(client, api_key, i + 1) for i in range(concurrency)]
        )

        print(f"\nRunning {min(3, concurrency)} concurrent non-streaming requests...")
        non_stream_results = await asyncio.gather(
            *[run_non_streaming_request(client, api_key, i + 1) for i in range(min(3, concurrency))]
        )

    wall_elapsed = time.perf_counter() - wall_start

    print("\n--- Streaming results ---")
    stream_ok = 0
    for result in stream_results:
        status = "OK" if result.ok else "FAIL"
        if result.ok:
            stream_ok += 1
        err = f" error={result.error}" if result.error else ""
        print(
            f"  #{result.request_id} {status} status={result.status_code} "
            f"events={result.event_count} time={result.elapsed_s:.2f}s{err}"
        )

    print("\n--- Non-streaming results ---")
    non_stream_ok = 0
    for result in non_stream_results:
        status = "OK" if result.ok else "FAIL"
        if result.ok:
            non_stream_ok += 1
        err = f" error={result.error}" if result.error else ""
        print(
            f"  #{result.request_id} {status} status={result.status_code} "
            f"time={result.elapsed_s:.2f}s{err}"
        )

    print("\n--- Summary ---")
    print(f"Streaming:     {stream_ok}/{concurrency} succeeded")
    print(f"Non-streaming: {non_stream_ok}/{len(non_stream_results)} succeeded")
    print(f"Total wall time: {wall_elapsed:.2f}s")

    if stream_ok != concurrency or non_stream_ok != len(non_stream_results):
        sys.exit(1)

    print("Concurrent streams OK")


if __name__ == "__main__":
    asyncio.run(main())
