"""extend cache_entries for L1 exact + L2 verified semantic cache

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cache_entries", sa.Column("fingerprint", sa.String(length=64), nullable=True))
    op.add_column("cache_entries", sa.Column("fingerprint_version", sa.Integer(), nullable=True))
    op.add_column(
        "cache_entries",
        sa.Column("request_messages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("cache_entries", sa.Column("temperature", sa.Float(), nullable=True))
    op.add_column("cache_entries", sa.Column("max_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "cache_entries", sa.Column("pii_values_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "cache_entries",
        sa.Column("exact_use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "cache_entries",
        sa.Column("semantic_use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_unique_constraint(
        "uq_cache_entries_project_fingerprint",
        "cache_entries",
        ["project_id", "fingerprint"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_cache_entries_project_fingerprint", "cache_entries", type_="unique")
    op.drop_column("cache_entries", "semantic_use_count")
    op.drop_column("cache_entries", "exact_use_count")
    op.drop_column("cache_entries", "pii_values_hash")
    op.drop_column("cache_entries", "max_tokens")
    op.drop_column("cache_entries", "temperature")
    op.drop_column("cache_entries", "request_messages")
    op.drop_column("cache_entries", "fingerprint_version")
    op.drop_column("cache_entries", "fingerprint")
