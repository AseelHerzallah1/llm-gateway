"""Verify model cost estimation (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.observability.cost import estimate_cost_usd, resolve_pricing


def main() -> None:
    assert resolve_pricing("gpt-4o-mini-2024-07-18") is not None
    assert resolve_pricing("gpt-4o") is not None
    assert resolve_pricing("unknown-model") is None

    cost = estimate_cost_usd("gpt-4o-mini", input_tokens=1000, output_tokens=500)
    expected = (1000 * 0.15 / 1_000_000) + (500 * 0.60 / 1_000_000)
    assert abs(cost - round(expected, 8)) < 1e-10, (cost, expected)

    assert estimate_cost_usd("unknown-model", 100, 50) == 0.0
    assert estimate_cost_usd("gpt-4o-mini", 0, 0) == 0.0

    print("Cost estimation OK")
    print(f"Example: 1000 in + 500 out on gpt-4o-mini = ${cost:.8f}")


if __name__ == "__main__":
    main()
