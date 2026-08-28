"""Fixtures for integration tests that require a live PostgreSQL database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.auth.api_keys import generate_api_key, prepare_stored_api_key
from app.cache.memory import InMemorySemanticCache
from app.config import settings
from app.db.models.cache_entry import CacheEntryRecord
from app.db.models.project import Project
from app.db.models.request import RequestLog
from app.db.models.user import User
from app.db.session import async_session_factory, engine, verify_db_connection
from app.errors import invalid_request_error
from app.main import app
from app.providers.router import resolve_provider_name
from tests.fakes.embeddings import DeterministicEmbeddingProvider
from tests.fakes.providers import RetryOnlyRouter, SuccessProvider
from tests.fakes.verifier import DeterministicVerifier
from tests.helpers import mock_app_state

_postgres_checked = False
_postgres_ok = False


@pytest.fixture
async def postgres_available() -> None:
    """Skip DB integration tests when PostgreSQL is unreachable."""
    global _postgres_checked, _postgres_ok
    if not _postgres_checked:
        try:
            await verify_db_connection()
            _postgres_ok = True
        except Exception:
            _postgres_ok = False
        _postgres_checked = True
    if not _postgres_ok:
        pytest.skip("PostgreSQL not available")


@pytest.fixture(autouse=True)
async def reset_db_engine_pool() -> AsyncIterator[None]:
    """Avoid asyncpg pool/event-loop bleed between DB integration tests."""
    yield
    await engine.dispose()


@pytest.fixture
async def db_project(postgres_available) -> AsyncIterator[tuple[Project, str]]:
    """Create an isolated user/project row and delete it after the test."""
    api_key = generate_api_key()
    lookup, key_hash = prepare_stored_api_key(api_key)
    email = f"pytest-{uuid.uuid4()}@local.dev"
    password_hash = bcrypt.hashpw(b"pytest", bcrypt.gensalt()).decode("utf-8")

    async with async_session_factory() as db:
        user = User(email=email, password_hash=password_hash)
        db.add(user)
        await db.flush()

        project = Project(
            user_id=user.id,
            name=f"pytest-{uuid.uuid4().hex[:8]}",
            api_key_lookup=lookup,
            api_key_hash=key_hash,
            active=True,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)

    try:
        yield project, api_key
    finally:
        async with async_session_factory() as db:
            await db.execute(delete(RequestLog).where(RequestLog.project_id == project.id))
            await db.execute(
                delete(CacheEntryRecord).where(CacheEntryRecord.project_id == project.id)
            )
            await db.execute(delete(Project).where(Project.id == project.id))
            await db.execute(delete(User).where(User.id == project.user_id))
            await db.commit()


@pytest.fixture
async def db_client(db_project, monkeypatch) -> AsyncIterator[tuple[AsyncClient, Project, str]]:
    """HTTP client with real DB auth and mocked external providers."""
    project, api_key = db_project
    mock_app_state(app, monkeypatch, resolve_provider_name=resolve_provider_name)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, project, api_key

    app.dependency_overrides.clear()


@pytest.fixture
async def db_cache_client(
    db_project, monkeypatch
) -> AsyncIterator[
    tuple[
        AsyncClient,
        Project,
        str,
        InMemorySemanticCache,
        SuccessProvider,
        DeterministicEmbeddingProvider,
        DeterministicVerifier,
    ]
]:
    """HTTP client with real semantic cache, deterministic embeddings, stub provider."""
    project, api_key = db_project
    mock_app_state(app, monkeypatch, resolve_provider_name=resolve_provider_name)

    cache = InMemorySemanticCache(candidate_threshold=settings.cache_candidate_threshold)
    embedding_provider = DeterministicEmbeddingProvider()
    verifier = DeterministicVerifier()
    provider = SuccessProvider("openai", content="from-provider")

    app.state.semantic_cache = cache
    app.state.embedding_provider = embedding_provider
    app.state.cache_verifier = verifier
    app.state.cache_verifier_client = AsyncMock()
    app.state.cache_verifier_client.aclose = AsyncMock()
    app.state.provider_router = RetryOnlyRouter(provider)

    monkeypatch.setattr("app.config.settings.semantic_cache_enabled", True)
    monkeypatch.setattr("app.config.settings.request_log_async", False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, project, api_key, cache, provider, embedding_provider, verifier

    app.dependency_overrides.clear()
