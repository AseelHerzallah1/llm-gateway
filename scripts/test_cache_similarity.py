"""Verify cosine similarity helper (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.similarity import cosine_similarity


def main() -> None:
    assert abs(cosine_similarity([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert abs(cosine_similarity([2.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9

    similar = cosine_similarity([1.0, 0.0], [0.99, 0.01])
    assert similar > 0.99

    print("Cosine similarity OK")


if __name__ == "__main__":
    main()
