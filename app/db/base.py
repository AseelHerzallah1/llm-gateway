"""SQLAlchemy declarative base for ORM models (Phase 2.6+)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all database models."""
