"""Manual test for OpenAI provider streaming (Task 4.1).

Usage (from project root):
    python scripts/test_openai_stream.py

Requires OPENAI_API_KEY in .env
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers.base import ChatMessage, CompletionRequest
from app.providers.openai import create_openai_provider


async def main() -> None:
    provider = create_openai_provider()
    request = CompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Count from 1 to 5, one number per line.")],
        max_tokens=50,
    )

    print("Streaming from OpenAI provider...")
    print("-" * 40)

    content_parts: list[str] = []
    event_count = 0

    try:
        async for sse_event in provider.stream(request):
            event_count += 1
            print(sse_event, end="", flush=True)

            line = sse_event.strip()
            if line == "data: [DONE]":
                continue
            if line.startswith("data: "):
                chunk = json.loads(line[6:])
                delta = chunk["choices"][0].get("delta", {})
                if delta.get("content"):
                    content_parts.append(delta["content"])
    finally:
        await provider.aclose()

    print("-" * 40)
    print(f"Events received: {event_count}")
    print("Assembled content:", "".join(content_parts).strip())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Test failed: {exc}", file=sys.stderr)
        sys.exit(1)
