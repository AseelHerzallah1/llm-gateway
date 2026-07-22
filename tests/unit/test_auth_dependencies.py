"""Unit tests for auth header parsing and project resolution."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.api_keys import generate_api_key, prepare_stored_api_key
from app.auth.dependencies import extract_api_key, resolve_project
from app.db.models.project import Project
from app.errors import GatewayHTTPException


@pytest.mark.unit
def test_extract_api_key_from_bearer() -> None:
    assert extract_api_key("Bearer gw-sk-test-key", None) == "gw-sk-test-key"


@pytest.mark.unit
def test_extract_api_key_from_x_api_key() -> None:
    assert extract_api_key(None, "gw-sk-test-key") == "gw-sk-test-key"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_project_with_bcrypt_key() -> None:
    api_key = generate_api_key()
    lookup, key_hash = prepare_stored_api_key(api_key)
    project = Project(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="test",
        api_key_lookup=lookup,
        api_key_hash=key_hash,
        active=True,
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value = iter([project])
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    resolved = await resolve_project(mock_db, api_key)
    assert resolved.id == project.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_project_rejects_invalid_key() -> None:
    mock_db = AsyncMock()
    with pytest.raises(GatewayHTTPException) as exc_info:
        await resolve_project(mock_db, "not-a-gateway-key")
    assert exc_info.value.status_code == 401


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_project_rejects_inactive_project() -> None:
    api_key = generate_api_key()
    lookup, key_hash = prepare_stored_api_key(api_key)
    project = Project(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="test",
        api_key_lookup=lookup,
        api_key_hash=key_hash,
        active=False,
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value = iter([project])
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(GatewayHTTPException) as exc_info:
        await resolve_project(mock_db, api_key)
    assert exc_info.value.body["error"]["code"] == "inactive_project"
