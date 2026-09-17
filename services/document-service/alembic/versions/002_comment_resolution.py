"""Add comment resolution fields.

Revision ID: 002
Revises: 001
Create Date: 2024-03-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "comments",
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "comments",
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("comments", "resolved_at")
    op.drop_column("comments", "resolved_by")
    op.drop_column("comments", "is_resolved")
