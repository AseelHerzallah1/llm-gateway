"""Manual test script for OpenAI provider (Task 3.2).

Usage (from project root):
    python scripts/test_openai_provider.py

Requires OPENAI_API_KEY in .env
"""

import asyncio
import sys
from pathlib import Path

# Allow imports from project root when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers.base import ChatMessage, CompletionRequest
from app.providers.openai import create_openai_provider


async def main() -> None:
    provider = create_openai_provider()

    request = CompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Say hello in one word.")],
        max_tokens=10,
    )

    try:
        response = await provider.complete(request)
    finally:
        await provider.aclose()

    print("Provider:", provider.name)
    print("Model:", response.model)
    print("Content:", response.content)
    print("Tokens:", response.total_tokens)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Test failed: {exc}", file=sys.stderr)
        sys.exit(1)
