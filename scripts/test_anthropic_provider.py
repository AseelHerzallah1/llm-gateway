"""Manual test script for Anthropic provider (Phase 7.1).

Usage:
    python scripts/test_anthropic_provider.py

Requires ANTHROPIC_API_KEY in .env
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers.anthropic import create_anthropic_provider
from app.providers.base import ChatMessage, CompletionRequest


async def main() -> None:
    provider = create_anthropic_provider()
    request = CompletionRequest(
        model="claude-3-5-haiku-20241022",
        messages=[
            ChatMessage(role="system", content="You are concise."),
            ChatMessage(role="user", content="Say hello in one word."),
        ],
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
