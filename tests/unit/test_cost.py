"""Unit tests for cost estimation."""

from __future__ import annotations

import pytest

from app.observability.cost import estimate_cost_usd, resolve_pricing


@pytest.mark.unit
def test_resolve_pricing_exact_match() -> None:
    pricing = resolve_pricing("gpt-4o-mini")
    assert pricing is not None
    assert pricing.input_per_token > 0


@pytest.mark.unit
def test_resolve_pricing_unknown_model() -> None:
    assert resolve_pricing("unknown-model") is None


@pytest.mark.unit
def test_estimate_cost_usd() -> None:
    cost = estimate_cost_usd("gpt-4o-mini", input_tokens=1000, output_tokens=500)
    assert cost > 0


@pytest.mark.unit
def test_estimate_cost_usd_zero_tokens() -> None:
    assert estimate_cost_usd("gpt-4o-mini", input_tokens=0, output_tokens=0) == 0.0
