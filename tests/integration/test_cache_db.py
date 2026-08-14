"""E2E semantic cache tests with real in-memory cache + PostgreSQL persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.cache.persistence import persist_cache_entry
from app.cache.types import new_cache_entry
from app.db.models.cache_entry import CacheEntryRecord
from app.db.models.request import RequestLog
from app.db.session import async_session_factory


pytestmark = [pytest.mark.integration, pytest.mark.db]


async def _chat(client, api_key: str, content: str) -> dict:
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": content}],
            "stream": False,
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_cache_miss_calls_provider_and_persists_entry(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider = db_cache_client

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
async def test_cache_hit_skips_provider_and_increments_use_count(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider = db_cache_client

    entry_id = await persist_cache_entry(
        project.id,
        "gpt-4o-mini",
        [1.0, 0.0, 0.0],
        "cached-paris-answer",
    )
    cache.load_entry(
        new_cache_entry(
            project.id,
            "gpt-4o-mini",
            [1.0, 0.0, 0.0],
            "cached-paris-answer",
            entry_id=entry_id,
        )
    )

    payload = await _chat(client, api_key, "What is Paris like?")

    assert payload["choices"][0]["message"]["content"] == "cached-paris-answer"
    assert provider.attempts == 0
    assert len(embedding_provider.calls) == 1

    async with async_session_factory() as db:
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalar_one()
        cache_row = (
            await db.execute(
                select(CacheEntryRecord).where(CacheEntryRecord.id == entry_id)
            )
        ).scalar_one()

    assert row.cache_hit is True
    assert cache_row.use_count == 1


@pytest.mark.asyncio
async def test_cache_similarity_below_threshold_is_miss(db_cache_client) -> None:
    client, project, api_key, cache, provider, _embedding_provider = db_cache_client

    entry_id = await persist_cache_entry(
        project.id,
        "gpt-4o-mini",
        [1.0, 0.0, 0.0],
        "paris-only",
    )
    cache.load_entry(
        new_cache_entry(
            project.id,
            "gpt-4o-mini",
            [1.0, 0.0, 0.0],
            "paris-only",
            entry_id=entry_id,
        )
    )

    payload = await _chat(client, api_key, "Tell me about London.")

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1

    async with async_session_factory() as db:
        row = (
            await db.execute(select(RequestLog).where(RequestLog.project_id == project.id))
        ).scalar_one()

    assert row.cache_hit is False


@pytest.mark.asyncio
async def test_empty_cache_skips_embed_on_lookup(db_cache_client) -> None:
    client, project, api_key, cache, provider, embedding_provider = db_cache_client

    assert cache.size == 0

    await _chat(client, api_key, "Tell me about Paris.")

    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 1
    assert cache.size == 1

    await _chat(client, api_key, "What is Paris like?")

    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 2


@pytest.mark.asyncio
async def test_pii_redacted_prompt_used_for_cache_embedding(db_cache_client, monkeypatch) -> None:
    """With PII enabled, semantic cache embeddings are built from redacted prompt text."""
    client, project, api_key, cache, provider, embedding_provider = db_cache_client
    raw_email = "aseel@example.com"

    monkeypatch.setattr("app.config.settings.pii_redaction_enabled", True)

    payload = await _chat(client, api_key, f"Contact {raw_email} about Paris.")

    assert payload["choices"][0]["message"]["content"] == "from-provider"
    assert provider.attempts == 1
    assert len(embedding_provider.calls) == 1
    assert raw_email not in embedding_provider.calls[0]
    assert "[EMAIL_1]" in embedding_provider.calls[0]
    assert cache.size == 1

    async with async_session_factory() as db:
        cache_count = (
            await db.execute(
                select(func.count())
                .select_from(CacheEntryRecord)
                .where(CacheEntryRecord.project_id == project.id)
            )
        ).scalar_one()

    assert cache_count == 1
