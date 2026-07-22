"""create api_key_lookup column for bcrypt auth

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("api_key_lookup", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_projects_api_key_lookup",
        "projects",
        ["api_key_lookup"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_projects_api_key_lookup", table_name="projects")
    op.drop_column("projects", "api_key_lookup")
