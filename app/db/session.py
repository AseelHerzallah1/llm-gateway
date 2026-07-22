"""Async database engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# echo=True logs SQL statements — useful in development only
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_size=10,
    max_overflow=10,
)

# Factory that creates a new database session per request
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def verify_db_connection() -> None:
    """Run a simple query to confirm PostgreSQL is reachable."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields one session, closes it after the request."""
    async with async_session_factory() as session:
        yield session


async def close_db() -> None:
    """Dispose of the connection pool on application shutdown."""
    await engine.dispose()
