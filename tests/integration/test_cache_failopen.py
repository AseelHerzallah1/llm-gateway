"""Fail-open behavior for gateway cache dependencies."""

from __future__ import annotations

import pytest

from tests.integration.test_cache_db import _chat, _seed_semantic_entry
from tests.fakes.embeddings import _CLUSTER_VECTORS, _cluster_for_text


def _cluster_vector(prompt: str) -> list[float]:
    return list(_CLUSTER_VECTORS[_cluster_for_text(prompt)])


pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.mark.asyncio
async def test_embedding_failure_falls_through_to_provider(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider, _ = db_cache_client

    await _seed_semantic_entry(
        project.id,
        cache,
        prompt="What is the capital of France?",
        response="Paris",
        embedding=[1.0, 0.0, 0.0],
    )
    embedding_provider.fail_next = True

    payload = await _chat(client, api_key, "Which city serves as France's capital?")

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1


@pytest.mark.asyncio
async def test_verifier_failure_falls_through_to_provider(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client

    await _seed_semantic_entry(
        project.id,
        cache,
        prompt="What is the capital of France?",
        response="Paris",
        embedding=_cluster_vector("What is the capital of France?"),
    )
    verifier.fail_open = True
    embedding_provider.calls.clear()

    payload = await _chat(client, api_key, "Which city serves as France's capital?")

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1


@pytest.mark.asyncio
async def test_verifier_malformed_output_falls_through(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client

    await _seed_semantic_entry(
        project.id,
        cache,
        prompt="What is the capital of France?",
        response="Paris",
        embedding=_cluster_vector("What is the capital of France?"),
    )
    verifier.malformed = True
    embedding_provider.calls.clear()

    payload = await _chat(client, api_key, "Which city serves as France's capital?")

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1


DANGEROUS_PAIRS = [
    (
        "How does OAuth authentication work?",
        "How does OAuth authorization work?",
    ),
    (
        "What does list.append do in Python?",
        "What does list.extend do in Python?",
    ),
    (
        "How do I sort a Python list?",
        "How do I reverse a Python list?",
    ),
    (
        "What are symptoms of type 1 diabetes?",
        "What are symptoms of type 2 diabetes?",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("prompt_a", "prompt_b"), DANGEROUS_PAIRS)
async def test_dangerous_semantic_pairs_rejected(
    db_cache_client,
    prompt_a: str,
    prompt_b: str,
) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client

    await _seed_semantic_entry(
        project.id,
        cache,
        prompt=prompt_a,
        response=f"cached answer for {prompt_a[:24]}",
        embedding=_cluster_vector(prompt_a),
    )
    embedding_provider.calls.clear()

    payload = await _chat(client, api_key, prompt_b)

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1
    assert len(verifier.calls) == 1
