"""Unit tests for cache similarity."""

from __future__ import annotations

import pytest

from app.cache.similarity import cosine_similarity


@pytest.mark.unit
def test_identical_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


@pytest.mark.unit
def test_orthogonal_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


@pytest.mark.unit
def test_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity([1.0], [1.0, 2.0])
