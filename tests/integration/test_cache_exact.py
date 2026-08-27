"""Integration tests focused on L1 exact cache behavior."""

from __future__ import annotations

import pytest

from app.cache.fingerprint import compute_fingerprint, pii_values_hash
from app.providers.base import ChatMessage
from tests.integration.test_cache_db import _chat


pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.mark.asyncio
async def test_different_model_is_miss(db_cache_client) -> None:
    client, _, api_key, _, provider, _, _ = db_cache_client
    prompt = "model isolation test"

    await _chat(client, api_key, prompt)
    await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
    )

    assert provider.attempts == 2


@pytest.mark.asyncio
async def test_different_system_message_is_miss(db_cache_client) -> None:
    client, _, api_key, _, provider, _, _ = db_cache_client
    user_content = "exact cache system message test"

    await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
        },
    )
    await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Be verbose."},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
        },
    )

    assert provider.attempts == 2


@pytest.mark.asyncio
async def test_different_pii_values_do_not_exact_hit(db_cache_client, monkeypatch) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)

    first = "Contact [EMAIL_1] about billing."
    second = "Contact [EMAIL_1] about billing."

    await _chat(client, api_key, "Contact aseel@example.com about billing.")
    await _chat(client, api_key, "Contact bob@example.com about billing.")

    fp_a = compute_fingerprint(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content=first)],
        temperature=None,
        max_tokens=None,
        token_map={"[EMAIL_1]": "aseel@example.com"},
    )
    fp_b = compute_fingerprint(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content=second)],
        temperature=None,
        max_tokens=None,
        token_map={"[EMAIL_1]": "bob@example.com"},
    )
    assert fp_a != fp_b
    assert provider.attempts == 2
    assert len(verifier.calls) == 0

    assert pii_values_hash({"[EMAIL_1]": "aseel@example.com"}) != pii_values_hash(
        {"[EMAIL_1]": "bob@example.com"}
    )
