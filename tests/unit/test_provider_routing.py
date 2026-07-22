"""Unit tests for model → provider routing rules."""

from __future__ import annotations

import pytest

from app.providers.router import resolve_provider_name


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o-mini", "openai"),
        ("o4-mini", "openai"),
        ("llama-3.3-70b-versatile", "groq"),
        ("mixtral-8x7b-32768", "groq"),
        ("claude-3-5-haiku-20241022", "anthropic"),
    ],
)
def test_resolve_provider_name(model: str, expected: str) -> None:
    assert resolve_provider_name(model) == expected


@pytest.mark.unit
def test_resolve_provider_name_unknown_model() -> None:
    with pytest.raises(ValueError, match="No provider routing rule"):
        resolve_provider_name("unknown-model-xyz")
