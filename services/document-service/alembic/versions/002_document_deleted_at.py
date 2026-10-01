"""Add documents.deleted_at for the trash listing.

Revision ID: 002
Revises: 001
Create Date: 2026-09-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_deleted_at() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == "deleted_at" for col in inspector.get_columns("documents"))


def upgrade() -> None:
    # init_db() may already have added the column on a running stack.
    if _has_deleted_at():
        return
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if _has_deleted_at():
        op.drop_column("documents", "deleted_at")
