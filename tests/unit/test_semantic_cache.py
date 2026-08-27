"""Unit tests for gateway cache memory store."""

from __future__ import annotations

import uuid

import pytest

from app.cache.fingerprint import compute_fingerprint
from app.cache.memory import InMemorySemanticCache
from app.cache.types import new_cache_entry
from app.providers.base import ChatMessage


@pytest.mark.unit
def test_has_semantic_entries_false_for_empty_cache() -> None:
    cache = InMemorySemanticCache(candidate_threshold=0.65)
    project_id = uuid.uuid4()
    assert not cache.has_semantic_entries(project_id, "gpt-4o-mini")


@pytest.mark.unit
def test_exact_lookup_is_o1() -> None:
    cache = InMemorySemanticCache(candidate_threshold=0.65)
    project_id = uuid.uuid4()
    messages = (ChatMessage(role="user", content="hello"),)
    fingerprint = compute_fingerprint(
        model="gpt-4o-mini",
        messages=list(messages),
        temperature=None,
        max_tokens=None,
        token_map={},
    )
    entry = new_cache_entry(
        project_id,
        "gpt-4o-mini",
        [1.0, 0.0, 0.0],
        "cached",
        fingerprint=fingerprint,
        request_messages=messages,
    )
    cache.load_entry(entry)
    assert cache.lookup_exact(project_id, fingerprint) is not None
    assert cache.lookup_exact(project_id, "missing") is None


@pytest.mark.unit
def test_semantic_candidate_skips_dimension_mismatch() -> None:
    cache = InMemorySemanticCache(candidate_threshold=0.65)
    project_id = uuid.uuid4()
    cache.load_entry(new_cache_entry(project_id, "gpt-4o-mini", [1.0, 0.0, 0.0], "short-dim"))
    cache.load_entry(
        new_cache_entry(
            project_id,
            "gpt-4o-mini",
            [1.0, 0.0, 0.0, 0.0],
            "long-dim",
            request_messages=(ChatMessage(role="user", content="long"),),
        )
    )

    candidate = cache.lookup_semantic_candidate(
        project_id,
        "gpt-4o-mini",
        [1.0, 0.0, 0.0, 0.0],
        temperature=None,
        max_tokens=None,
    )
    assert candidate is not None
    assert candidate.entry.response == "long-dim"


@pytest.mark.unit
def test_has_semantic_entries_true_after_store() -> None:
    cache = InMemorySemanticCache(candidate_threshold=0.65)
    project_id = uuid.uuid4()
    entry = new_cache_entry(
        project_id,
        "gpt-4o-mini",
        [1.0, 0.0],
        "hello",
        request_messages=(ChatMessage(role="user", content="hello"),),
    )
    cache.load_entry(entry)
    assert cache.has_semantic_entries(project_id, "gpt-4o-mini")
    assert not cache.has_semantic_entries(project_id, "gpt-4o")
