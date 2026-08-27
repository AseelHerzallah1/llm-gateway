"""Integration tests for L2 verified semantic cache positive cases."""

from __future__ import annotations

import pytest

from tests.fakes.embeddings import _CLUSTER_VECTORS, _cluster_for_text
from tests.integration.test_cache_db import _chat, _seed_semantic_entry


def _cluster_vector(prompt: str) -> list[float]:
    return list(_CLUSTER_VECTORS[_cluster_for_text(prompt)])


pytestmark = [pytest.mark.integration, pytest.mark.db]


CLASS_A_PAIRS = [
    (
        "Why is HTTPS safer than HTTP?",
        "What makes HTTPS more secure than HTTP?",
        "HTTPS encrypts traffic between browser and server.",
    ),
    (
        "What is the capital of France?",
        "Which city serves as France's capital?",
        "The capital of France is Paris.",
    ),
    (
        "Explain what a Python decorator does.",
        "What is the purpose of decorators in Python?",
        "Decorators wrap functions to modify behavior.",
    ),
    (
        "How does WiFi work?",
        "Explain how wireless networking works.",
        "WiFi uses radio waves to connect devices to a router.",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("prompt_a", "prompt_b", "response"), CLASS_A_PAIRS)
async def test_verified_semantic_class_a_pairs(
    db_cache_client,
    prompt_a: str,
    prompt_b: str,
    response: str,
) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client

    await _seed_semantic_entry(
        project.id,
        cache,
        prompt=prompt_a,
        response=response,
        embedding=_cluster_vector(prompt_a),
    )
    embedding_provider.calls.clear()

    payload = await _chat(client, api_key, prompt_b)

    assert payload["choices"][0]["message"]["content"] == response
    assert provider.attempts == 0
    assert len(embedding_provider.calls) == 1
    assert len(verifier.calls) == 1
