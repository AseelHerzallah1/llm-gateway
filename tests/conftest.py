"""Pytest fixtures for unit and integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_current_project
from app.db.models.project import Project
from app.errors import invalid_request_error
from app.main import app
from app.providers.router import resolve_provider_name
from tests.helpers import make_project


@pytest.fixture
def test_project() -> Project:
    return make_project()


@pytest.fixture
async def client(monkeypatch, test_project):
    """HTTP client with startup hooks mocked — no live PostgreSQL required."""

    mock_embedding = AsyncMock()
    mock_embedding.name = "mock-embeddings"
    mock_embedding.aclose = AsyncMock()

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
    mock_cache.similarity_threshold = 0.92
    mock_cache.lookup = MagicMock(return_value=None)

    app.state.provider_router = mock_router
    app.state.semantic_cache = mock_cache
    app.state.embedding_provider = mock_embedding

    async def override_project():
        return test_project

    app.dependency_overrides[get_current_project] = override_project

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    app.dependency_overrides.clear()
