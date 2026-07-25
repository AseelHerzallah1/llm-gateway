"""Integration tests for API key auth against PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.dependencies import resolve_project
from app.db.models.project import Project
from app.db.session import async_session_factory
from app.errors import GatewayHTTPException


pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.mark.asyncio
async def test_resolve_project_with_real_bcrypt_key(db_project) -> None:
    project, api_key = db_project

    async with async_session_factory() as db:
        resolved = await resolve_project(db, api_key)

    assert resolved.id == project.id
    assert resolved.name == project.name


@pytest.mark.asyncio
async def test_resolve_project_rejects_unknown_key(postgres_available) -> None:
    async with async_session_factory() as db:
        with pytest.raises(GatewayHTTPException) as exc_info:
            await resolve_project(db, "gw-sk-invalid-key-for-pytest")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_resolve_project_rejects_inactive_project(db_project) -> None:
    project, api_key = db_project

    async with async_session_factory() as db:
        stored = await db.get(Project, project.id)
        assert stored is not None
        stored.active = False
        await db.commit()

    async with async_session_factory() as db:
        with pytest.raises(GatewayHTTPException) as exc_info:
            await resolve_project(db, api_key)
    assert exc_info.value.body["error"]["code"] == "inactive_project"

    async with async_session_factory() as db:
        stored = await db.get(Project, project.id)
        assert stored is not None
        stored.active = True
        await db.commit()
