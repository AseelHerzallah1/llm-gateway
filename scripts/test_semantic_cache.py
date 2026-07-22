"""Verify in-memory semantic cache lookup (offline)."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.memory import InMemorySemanticCache


def main() -> None:
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()
    cache = InMemorySemanticCache(similarity_threshold=0.92)

    prompt_vec = [1.0, 0.0, 0.0]
    near_vec = [0.995, 0.05, 0.0]
    far_vec = [0.0, 1.0, 0.0]

    cache.store(project_a, "gpt-4o-mini", prompt_vec, "Paris is the capital of France.")

    hit = cache.lookup(project_a, "gpt-4o-mini", near_vec)
    assert hit is not None, "Expected cache hit for similar embedding"
    assert "Paris" in hit.response
    assert hit.similarity >= 0.92

    assert cache.lookup(project_a, "gpt-4o-mini", far_vec) is None
    assert cache.lookup(project_b, "gpt-4o-mini", near_vec) is None
    assert cache.lookup(project_a, "gpt-4o", near_vec) is None

    cache.clear()
    assert cache.size == 0
    assert cache.lookup(project_a, "gpt-4o-mini", prompt_vec) is None

    print("Semantic cache OK")


if __name__ == "__main__":
    main()
