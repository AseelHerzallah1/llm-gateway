"""Unit tests for verifier output parsing."""

from __future__ import annotations

import pytest

from app.cache.verifier import parse_verifier_output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        (" false ", False),
        ("TRUE", True),
        ("FALSE", False),
    ],
)
def test_accepts_literal_boolean_strings(raw: str, expected: bool) -> None:
    assert parse_verifier_output(raw) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "maybe",
        '{"reuse": true}',
        "true — looks good",
        "yes",
        "",
    ],
)
def test_rejects_non_literal_output(raw: str) -> None:
    assert parse_verifier_output(raw) is None
