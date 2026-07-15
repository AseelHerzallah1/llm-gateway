"""Manual HTTP test for streaming POST /v1/chat/completions.

Usage:
    python scripts/test_chat_stream.py <gateway-api-key>

Or set GATEWAY_TEST_API_KEY in .env
Requires uvicorn running on http://127.0.0.1:8001
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
        print("Usage: python scripts/test_chat_stream.py <gateway-api-key>")
        print("Or set GATEWAY_TEST_API_KEY in .env")
        sys.exit(1)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Count from 1 to 3, one number per line."}],
        "stream": True,
        "max_tokens": 30,
    }

    print("Streaming from gateway...")
    print("-" * 40)

    event_count = 0
    saw_done = False

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        ) as response:
            print("Status:", response.status_code)
            print("Content-Type:", response.headers.get("content-type"))
            if response.status_code != 200:
                print("Body:", await response.aread())
                sys.exit(1)

            async for line in response.aiter_lines():
                if not line:
                    continue
                print(line)
                event_count += 1
                if line.strip() == "data: [DONE]":
                    saw_done = True

    print("-" * 40)
    print(f"Events received: {event_count}")
    print("Saw [DONE]:", saw_done)

    if not saw_done:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
