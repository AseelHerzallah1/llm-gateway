"""Shared helpers for the pytest suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.db.models.project import Project


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
