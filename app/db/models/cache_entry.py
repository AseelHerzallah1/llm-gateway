"""Cache entry model — persisted gateway cache rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CacheEntryRecord(Base):
    """One stored request fingerprint/embedding and its cached LLM response."""

    __tablename__ = "cache_entries"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_cache_entries_project_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_messages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pii_values_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    cached_response: Mapped[str] = mapped_column(Text, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exact_use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    semantic_use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="cache_entries")
