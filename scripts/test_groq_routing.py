"""E2E test — route Groq models through the gateway.

Usage:
    python scripts/test_groq_routing.py <gateway-api-key>

Requires uvicorn on http://127.0.0.1:8001 and GROQ_API_KEY in .env.
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
        print("Usage: python scripts/test_groq_routing.py <gateway-api-key>")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "stream": False,
        "max_tokens": 10,
    }

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        response = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60.0,
        )

    if response.status_code != 200:
        print("Groq routing request failed:", response.status_code, response.text)
        sys.exit(1)

    data = response.json()
    content = data["choices"][0]["message"]["content"]
    print("Groq routing OK")
    print("Model:", data.get("model"))
    print("Content:", content)


if __name__ == "__main__":
    asyncio.run(main())
