"""Manual test for Anthropic provider streaming (Phase 7.1).

Usage:
    python scripts/test_anthropic_stream.py

Requires ANTHROPIC_API_KEY in .env
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers.anthropic import create_anthropic_provider
from app.providers.base import ChatMessage, CompletionRequest


async def main() -> None:
    provider = create_anthropic_provider()
    request = CompletionRequest(
        model="claude-3-5-haiku-20241022",
        messages=[ChatMessage(role="user", content="Count from 1 to 3, one number per line.")],
        max_tokens=30,
    )

    print("Streaming from Anthropic provider...")
    print("-" * 40)

    content_parts: list[str] = []
    event_count = 0
    saw_done = False

    try:
        async for sse_event in provider.stream(request):
            event_count += 1
            print(sse_event, end="", flush=True)

            line = sse_event.strip()
            if line == "data: [DONE]":
                saw_done = True
                continue
            if line.startswith("data: "):
                chunk = json.loads(line[6:])
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                if delta.get("content"):
                    content_parts.append(delta["content"])
    finally:
        await provider.aclose()

    print("-" * 40)
    print(f"Events received: {event_count}")
    print("Assembled content:", "".join(content_parts).strip())

    if not saw_done:
        print("Expected [DONE] event")
        sys.exit(1)

    print("Anthropic provider stream OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Test failed: {exc}", file=sys.stderr)
        sys.exit(1)
