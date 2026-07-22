"""Cosine similarity for embedding vectors (pure Python, no numpy)."""

from __future__ import annotations

import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [-1.0, 1.0]. Raises on dimension mismatch."""
    if len(a) != len(b):
        raise ValueError(f"Embedding dimension mismatch: {len(a)} vs {len(b)}")

    if not a:
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for left, right in zip(a, b, strict=True):
        dot += left * right
        norm_a += left * left
        norm_b += right * right

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
