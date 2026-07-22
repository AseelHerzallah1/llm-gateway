"""Unit tests for metrics helpers."""

from __future__ import annotations

import pytest

from app.observability.metrics import percentile


@pytest.mark.unit
def test_percentile_empty() -> None:
    assert percentile([], 50) == 0


@pytest.mark.unit
def test_percentile_single_value() -> None:
    assert percentile([42], 50) == 42


@pytest.mark.unit
def test_percentile_median() -> None:
    assert percentile([10, 20, 30], 50) == 20


@pytest.mark.unit
def test_percentile_p95() -> None:
    assert percentile([100, 200, 300, 400], 95) == 385


@pytest.mark.unit
def test_percentile_p99() -> None:
    assert percentile(list(range(1, 11)), 99) == 9
