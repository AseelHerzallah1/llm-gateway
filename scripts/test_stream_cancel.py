"""Simulate client disconnect mid-stream to verify upstream cancellation.

Usage:
    python scripts/test_stream_cancel.py <gateway-api-key>

Requires uvicorn on http://127.0.0.1:8001.
Watch the server logs for "Client disconnected mid-stream" or "Stream task cancelled".
"""

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
        print("Usage: python scripts/test_stream_cancel.py <gateway-api-key>")
        sys.exit(1)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": "Write a long story about a robot learning to paint. At least 500 words.",
            }
        ],
        "stream": True,
        "max_tokens": 500,
    }

    print("Starting stream, will disconnect after a few events...")
    event_count = 0

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        ) as response:
            if response.status_code != 200:
                print("Unexpected status:", response.status_code)
                print(await response.aread())
                sys.exit(1)

            async for line in response.aiter_lines():
                if line:
                    print(line[:80] + ("..." if len(line) > 80 else ""))
                    event_count += 1
                if event_count >= 5:
                    print("-" * 40)
                    print(f"Disconnecting after {event_count} events (simulated client drop)")
                    break

    print("Client closed connection.")
    print("Check uvicorn logs for upstream cancellation message.")


if __name__ == "__main__":
    asyncio.run(main())
