"""Unit tests for semantic cache memory store."""

from __future__ import annotations

import uuid

import pytest

from app.cache.memory import InMemorySemanticCache
from app.cache.types import new_cache_entry


@pytest.mark.unit
def test_has_entries_false_for_empty_cache() -> None:
    cache = InMemorySemanticCache(similarity_threshold=0.92)
    project_id = uuid.uuid4()
    assert not cache.has_entries(project_id, "gpt-4o-mini")


@pytest.mark.unit
def test_has_entries_true_after_store() -> None:
    cache = InMemorySemanticCache(similarity_threshold=0.92)
    project_id = uuid.uuid4()
    entry = new_cache_entry(project_id, "gpt-4o-mini", [1.0, 0.0], "hello")
    cache.load_entry(entry)
    assert cache.has_entries(project_id, "gpt-4o-mini")
    assert not cache.has_entries(project_id, "gpt-4o")
