"""Resolve authenticated project from request headers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import hash_api_key, is_valid_api_key_format
from app.db.models.project import Project
from app.db.session import async_session_factory
from app.errors import inactive_project_error, invalid_api_key_error


def extract_api_key(
    authorization: str | None,
    x_api_key: str | None,
) -> str | None:
    """Read API key from Authorization Bearer or X-API-Key header."""
    if x_api_key:
        return x_api_key.strip()

    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    return None


async def resolve_project(db: AsyncSession, raw_api_key: str | None) -> Project:
    """Validate API key and return the matching project."""
    if not raw_api_key or not is_valid_api_key_format(raw_api_key):
        raise invalid_api_key_error()

    key_hash = hash_api_key(raw_api_key)
    result = await db.execute(select(Project).where(Project.api_key_hash == key_hash))
    project = result.scalar_one_or_none()

    if project is None:
        raise invalid_api_key_error()

    if not project.active:
        raise inactive_project_error()

    return project


async def get_current_project(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Project:
    """FastAPI dependency — auth lookup uses a short-lived DB session.

    The session closes before the route handler runs so long-lived streaming
    responses do not hold a PostgreSQL connection for their entire duration.
    """
    raw_api_key = extract_api_key(authorization, x_api_key)
    async with async_session_factory() as db:
        project = await resolve_project(db, raw_api_key)
        await db.refresh(project)
        db.expunge(project)
        return project
