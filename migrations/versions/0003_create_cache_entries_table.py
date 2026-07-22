"""create cache_entries table

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cache_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("embedding", postgresql.JSONB(), nullable=False),
        sa.Column("cached_response", sa.Text(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cache_entries_project_id", "cache_entries", ["project_id"])
    op.create_index(
        "ix_cache_entries_project_id_model",
        "cache_entries",
        ["project_id", "model"],
    )


def downgrade() -> None:
    op.drop_index("ix_cache_entries_project_id_model", table_name="cache_entries")
    op.drop_index("ix_cache_entries_project_id", table_name="cache_entries")
    op.drop_table("cache_entries")
