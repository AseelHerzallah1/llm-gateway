"""Verify OpenAI embedding provider.

Usage:
    python scripts/test_embeddings.py

Requires OPENAI_API_KEY in .env
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.embeddings.openai import create_openai_embedding_provider
from app.embeddings.prompt import messages_to_embed_text
from app.providers.base import ChatMessage


def _vectors_close(a: list[float], b: list[float], tol: float = 1e-6) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


async def main() -> None:
    provider = create_openai_embedding_provider()
    text = messages_to_embed_text(
        [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="What is the capital of France?"),
        ]
    )

    try:
        vector_a = await provider.embed(text)
        vector_b = await provider.embed(text)
        different = await provider.embed("What is the capital of Germany?")
    finally:
        await provider.aclose()

    if len(vector_a) < 100:
        print("Expected embedding dimension >= 100, got", len(vector_a))
        sys.exit(1)

    if vector_a != vector_b:
        if not _vectors_close(vector_a, vector_b):
            print("Identical text should produce identical embeddings")
            sys.exit(1)

    if _vectors_close(vector_a, different):
        print("Different prompts should not produce identical embeddings")
        sys.exit(1)

    print("Embeddings OK")
    print("Dimension:", len(vector_a))
    print("Sample:", vector_a[:3])


if __name__ == "__main__":
    asyncio.run(main())
