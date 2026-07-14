"""Manual HTTP test for POST /v1/chat/completions.

Usage:
    python scripts/test_chat_completions.py

Reads GATEWAY_TEST_API_KEY from .env (via app settings) or pass as argument.
"""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings


async def main() -> None:
    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    if not api_key:
        from dotenv import load_dotenv

        load_dotenv()
        import os

        api_key = os.getenv("GATEWAY_TEST_API_KEY", "")

    if not api_key:
        print("Usage: python scripts/test_chat_completions.py <gateway-api-key>")
        print("Or set GATEWAY_TEST_API_KEY in .env")
        sys.exit(1)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "stream": False,
        "max_tokens": 10,
    }

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
        response = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    print("Status:", response.status_code)
    print("Body:", response.text)

    if response.status_code != 200:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
