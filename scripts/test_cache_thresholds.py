"""Measure embedding similarity for cache threshold tuning.

Usage:
    python scripts/test_cache_thresholds.py

Requires OPENAI_API_KEY in .env. Prints similarities and hit/miss at 0.92.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.similarity import cosine_similarity
from app.cache.threshold_pairs import DEFAULT_THRESHOLD, PROMPT_PAIRS
from app.embeddings.openai import create_openai_embedding_provider


async def main() -> None:
    provider = create_openai_embedding_provider()
    unique_prompts = sorted({pair.prompt_a for pair in PROMPT_PAIRS} | {pair.prompt_b for pair in PROMPT_PAIRS})
    vectors: dict[str, list[float]] = {}

    try:
        for prompt in unique_prompts:
            vectors[prompt] = await provider.embed(prompt)
    finally:
        await provider.aclose()

    print(f"Threshold tuning (default={DEFAULT_THRESHOLD})")
    print("-" * 72)

    mismatches = 0
    for pair in PROMPT_PAIRS:
        similarity = cosine_similarity(vectors[pair.prompt_a], vectors[pair.prompt_b])
        would_hit = similarity >= DEFAULT_THRESHOLD
        ok = would_hit == pair.expect_hit_at_092
        if not ok:
            mismatches += 1

        status = "OK" if ok else "MISMATCH"
        decision = "HIT" if would_hit else "MISS"
        print(f"[{status}] {pair.label} ({pair.category})")
        print(f"  A: {pair.prompt_a}")
        print(f"  B: {pair.prompt_b}")
        print(f"  similarity={similarity:.4f} -> {decision} at {DEFAULT_THRESHOLD}")
        print()

    print("-" * 72)
    if mismatches:
        print(f"Finished with {mismatches} mismatch(es) at threshold {DEFAULT_THRESHOLD}")
        sys.exit(1)

    print("Threshold tuning OK — safety pairs miss and identical prompts hit at 0.92")
    print("See docs/CACHE_TUNING.md for paraphrase trade-offs.")


if __name__ == "__main__":
    asyncio.run(main())
