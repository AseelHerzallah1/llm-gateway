"""Estimate USD cost from model name and token usage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """Per-token rates in USD (input and output)."""

    input_per_token: float
    output_per_token: float


# OpenAI list prices — update when provider pricing changes.
# Keys are matched as prefixes against the model string returned by the API.
MODEL_PRICING: dict[str, ModelPricing] = {
    "gpt-4o-mini": ModelPricing(
        input_per_token=0.15 / 1_000_000,
        output_per_token=0.60 / 1_000_000,
    ),
    "gpt-4o": ModelPricing(
        input_per_token=2.50 / 1_000_000,
        output_per_token=10.00 / 1_000_000,
    ),
    "gpt-3.5-turbo": ModelPricing(
        input_per_token=0.50 / 1_000_000,
        output_per_token=1.50 / 1_000_000,
    ),
}


def resolve_pricing(model: str) -> ModelPricing | None:
    """Find the best matching pricing entry for a model name."""
    normalized = model.strip().lower()
    matches = [key for key in MODEL_PRICING if normalized.startswith(key)]
    if not matches:
        return None
    best_key = max(matches, key=len)
    return MODEL_PRICING[best_key]


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate request cost from token counts and configured model rates."""
    pricing = resolve_pricing(model)
    if pricing is None or (input_tokens == 0 and output_tokens == 0):
        return 0.0

    cost = (
        input_tokens * pricing.input_per_token + output_tokens * pricing.output_per_token
    )
    return round(cost, 8)
