"""Pytest fixtures for unit and integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_current_project
from app.main import app
from app.providers.router import resolve_provider_name
from tests.helpers import make_project, mock_app_state


@pytest.fixture(autouse=True)
def isolated_prometheus_registry():
    """Avoid duplicate metric registration across tests."""
    from prometheus_client import CollectorRegistry

    from app.observability.prometheus_metrics import reset_prometheus_metrics_for_tests

    reset_prometheus_metrics_for_tests(CollectorRegistry())
    yield


@pytest.fixture
def test_project():
    return make_project()


@pytest.fixture
async def client(monkeypatch, test_project):
    """HTTP client with startup hooks mocked — no live PostgreSQL required."""
    mock_app_state(app, monkeypatch, resolve_provider_name=resolve_provider_name)

    async def override_project():
        return test_project

    app.dependency_overrides[get_current_project] = override_project

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    app.dependency_overrides.clear()
