"""E2E gateway cache tests with real in-memory cache + PostgreSQL persistence."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.cache.fingerprint import FINGERPRINT_VERSION, compute_fingerprint, pii_values_hash
from app.cache.memory import GatewayCache
from app.cache.persistence import hydrate_gateway_cache, persist_cache_entry
from app.cache.types import new_cache_entry
from app.db.models.cache_entry import CacheEntryRecord
from app.db.models.request import RequestLog
from app.db.session import async_session_factory
from app.providers.base import ChatMessage


pytestmark = [pytest.mark.integration, pytest.mark.db]


def _chat_body(content: str, **extra) -> dict:
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": content}],
        "stream": False,
    }
    body.update(extra)
    return body


async def _chat(client, api_key: str, content: str, **extra) -> dict:
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=_chat_body(content, **extra),
    )
    assert response.status_code == 200
    return response.json()


async def _seed_semantic_entry(
    project_id: uuid.UUID,
    cache: GatewayCache,
    *,
    prompt: str,
    response: str,
    embedding: list[float],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> uuid.UUID:
    messages = (ChatMessage(role="user", content=prompt),)
    fingerprint = compute_fingerprint(
        model="gpt-4o-mini",
        messages=list(messages),
        temperature=temperature,
        max_tokens=max_tokens,
        token_map={},
    )
    entry = new_cache_entry(
        project_id,
        "gpt-4o-mini",
        embedding,
        response,
        fingerprint=fingerprint,
        fingerprint_version=FINGERPRINT_VERSION,
        request_messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        pii_values_hash=pii_values_hash({}),
    )
    entry_id = await persist_cache_entry(entry)
    cache.load_entry(
        new_cache_entry(
            project_id,
            "gpt-4o-mini",
            embedding,
            response,
            entry_id=entry_id,
            fingerprint=fingerprint,
            fingerprint_version=FINGERPRINT_VERSION,
            request_messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            pii_values_hash=pii_values_hash({}),
        )
    )
    return entry_id


@pytest.mark.asyncio
async def test_cache_miss_calls_provider_and_persists_entry(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider, _verifier = db_cache_client

    payload = await _chat(client, api_key, "Tell me about Paris.")

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 1
    assert cache.size == 1

    async with async_session_factory() as db:
        cache_count = (
            await db.execute(
                select(func.count())
                .select_from(CacheEntryRecord)
                .where(CacheEntryRecord.project_id == project.id)
            )
        ).scalar_one()
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalar_one()

    assert cache_count == 1
    assert row.cache_hit is False
    assert row.status == "success"


@pytest.mark.asyncio
async def test_exact_cache_hit_skips_provider_embed_and_verifier(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client
    prompt = "cache metrics exact hit test"

    await _chat(client, api_key, prompt)
    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 1
    assert len(verifier.calls) == 0

    payload = await _chat(client, api_key, prompt)
    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 1
    assert len(verifier.calls) == 0

    async with async_session_factory() as db:
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalars().all()

    assert any(r.cache_hit for r in row)


@pytest.mark.asyncio
async def test_different_temperature_is_miss(db_cache_client) -> None:
    client, _, api_key, _, provider, _, _ = db_cache_client
    prompt = "temperature sensitivity test"

    await _chat(client, api_key, prompt, temperature=0.2)
    await _chat(client, api_key, prompt, temperature=0.8)

    assert provider.attempts == 2


@pytest.mark.asyncio
async def test_different_max_tokens_is_miss(db_cache_client) -> None:
    client, _, api_key, _, provider, _, _ = db_cache_client
    prompt = "max tokens sensitivity test"

    await _chat(client, api_key, prompt, max_tokens=64)
    await _chat(client, api_key, prompt, max_tokens=128)

    assert provider.attempts == 2


@pytest.mark.asyncio
async def test_verified_semantic_hit_skips_provider(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client

    entry_id = await _seed_semantic_entry(
        project.id,
        cache,
        prompt="What is the capital of France?",
        response="The capital of France is Paris.",
        embedding=[1.0, 0.0, 0.0],
    )
    embedding_provider.calls.clear()

    payload = await _chat(client, api_key, "Which city serves as France's capital?")

    assert payload["choices"][0]["message"]["content"] == "The capital of France is Paris."
    assert provider.attempts == 0
    assert len(embedding_provider.calls) == 1
    assert len(verifier.calls) == 1

    async with async_session_factory() as db:
        cache_row = (
            await db.execute(select(CacheEntryRecord).where(CacheEntryRecord.id == entry_id))
        ).scalar_one()
    assert cache_row.semantic_use_count == 1


@pytest.mark.asyncio
async def test_semantic_reject_calls_provider(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client

    await _seed_semantic_entry(
        project.id,
        cache,
        prompt="How does OAuth authentication work?",
        response="OAuth authentication grants access tokens.",
        embedding=[0.8485586743408395, 0.5291012910595824, 0.0],
    )
    embedding_provider.calls.clear()

    payload = await _chat(client, api_key, "How does OAuth authorization work?")

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 1
    assert len(verifier.calls) == 1


@pytest.mark.asyncio
async def test_pii_detected_skips_semantic_reuse(db_cache_client, monkeypatch) -> None:
    client, project, api_key, cache, provider, embedding_provider, verifier = db_cache_client
    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)

    await _seed_semantic_entry(
        project.id,
        cache,
        prompt="What is the capital of France?",
        response="The capital of France is Paris.",
        embedding=[1.0, 0.0, 0.0],
    )
    embedding_provider.calls.clear()

    payload = await _chat(client, api_key, "Email aseel@example.com about France's capital.")

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1
    assert len(verifier.calls) == 0
    assert len(embedding_provider.calls) == 1


@pytest.mark.asyncio
async def test_restart_hydration_preserves_exact_hit(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider, _ = db_cache_client
    prompt = "hydration exact hit test"

    await _chat(client, api_key, prompt)
    assert provider.attempts == 1

    reloaded = GatewayCache(candidate_threshold=cache.candidate_threshold)
    await hydrate_gateway_cache(reloaded)

    fingerprint = compute_fingerprint(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content=prompt)],
        temperature=None,
        max_tokens=None,
        token_map={},
    )
    assert reloaded.lookup_exact(project.id, fingerprint) is not None

    from app.main import app

    app.state.semantic_cache = reloaded
    embedding_provider.calls.clear()

    await _chat(client, api_key, prompt)
    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 0
