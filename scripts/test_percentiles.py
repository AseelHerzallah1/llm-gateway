"""Verify percentile helper (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.observability.metrics import percentile


def main() -> None:
    assert percentile([], 50) == 0
    assert percentile([42], 50) == 42
    assert percentile([10, 20, 30], 50) == 20
    assert percentile([100, 200, 300, 400], 95) == 385
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 99) == 9

    print("Percentile helper OK")


if __name__ == "__main__":
    main()
