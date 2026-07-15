"""create requests table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error_reason", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requests_project_id", "requests", ["project_id"])
    op.create_index("ix_requests_created_at", "requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_requests_created_at", table_name="requests")
    op.drop_index("ix_requests_project_id", table_name="requests")
    op.drop_table("requests")
