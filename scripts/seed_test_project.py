"""Seed a test user and project for API key auth testing.

Usage:
    python scripts/seed_test_project.py

Prints the API key once — save it for testing Task 3.4+.
"""

import asyncio
import sys
from pathlib import Path

import bcrypt
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.api_keys import generate_api_key, hash_api_key
from app.db.models.project import Project
from app.db.models.user import User
from app.db.session import async_session_factory


async def main() -> None:
    api_key = generate_api_key()
    password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8")

    async with async_session_factory() as db:
        existing = await db.execute(select(User).where(User.email == "admin@local.dev"))
        if existing.scalar_one_or_none():
            print("Test user already exists. Delete rows manually or use existing key.")
            return

        user = User(email="admin@local.dev", password_hash=password_hash)
        db.add(user)
        await db.flush()

        project = Project(
            user_id=user.id,
            name="test-project",
            api_key_hash=hash_api_key(api_key),
            active=True,
        )
        db.add(project)
        await db.commit()

    print("Seeded test project successfully.")
    print("Project name: test-project")
    print("API key (save this — shown once):")
    print(api_key)


if __name__ == "__main__":
    asyncio.run(main())
