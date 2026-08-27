"""Shared helpers for the pytest suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI

from app.db.models.project import Project
from app.errors import invalid_request_error
from tests.fakes.verifier import DeterministicVerifier


def make_project(*, active: bool = True) -> Project:
    return Project(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="test-project",
        api_key_lookup="testlookup12",
        api_key_hash="$2b$12$abcdefghijklmnopqrstuv",  # not verified in most tests
        active=active,
        created_at=datetime.now(timezone.utc),
    )


def mock_app_state(
    app: FastAPI,
    monkeypatch,
    *,
    resolve_provider_name,
) -> MagicMock:
    """Attach mocked provider/cache state to the app for HTTP integration tests."""
    mock_embedding = AsyncMock()
    mock_embedding.name = "mock-embeddings"
    mock_embedding.aclose = AsyncMock()
    mock_embedding.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])

    mock_provider = MagicMock()
    mock_provider.name = "openai"

    mock_router = MagicMock()
    mock_router.provider_names = ["openai"]

    def mock_get_provider(model: str):
        try:
            resolve_provider_name(model)
        except ValueError as exc:
            raise invalid_request_error(str(exc)) from exc
        return mock_provider

    mock_router.get_provider = MagicMock(side_effect=mock_get_provider)
    mock_router.aclose = AsyncMock()

    mock_cache = MagicMock()
    mock_cache.candidate_threshold = 0.65
    mock_cache.lookup_exact = MagicMock(return_value=None)
    mock_cache.has_semantic_entries = MagicMock(return_value=False)
    mock_cache.lookup_semantic_candidate = MagicMock(return_value=None)
    mock_cache.upsert_entry = MagicMock()
    mock_cache.size = 0

    mock_verifier_client = AsyncMock()
    mock_verifier_client.aclose = AsyncMock()
    mock_verifier = DeterministicVerifier()

    monkeypatch.setattr("app.main.verify_db_connection", AsyncMock())
    monkeypatch.setattr("app.main.hydrate_gateway_cache", AsyncMock(return_value=0))
    monkeypatch.setattr("app.main.close_db", AsyncMock())
    monkeypatch.setattr("app.main.create_provider_router", lambda: mock_router)
    monkeypatch.setattr("app.main.create_gateway_cache", lambda: mock_cache)
    monkeypatch.setattr("app.main.create_openai_embedding_provider", lambda: mock_embedding)
    monkeypatch.setattr("app.main.create_verifier_client", lambda: mock_verifier_client)

    app.state.provider_router = mock_router
    app.state.semantic_cache = mock_cache
    app.state.embedding_provider = mock_embedding
    app.state.cache_verifier = mock_verifier
    app.state.cache_verifier_client = mock_verifier_client

    return mock_router
