"""Add documents.deleted_at for the trash view.

Revision ID: 002
Revises: 001
Create Date: 2026-09-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_deleted_at() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("documents")
    return any(column["name"] == "deleted_at" for column in columns)


def upgrade() -> None:
    # The service backfills nullable model columns at startup, so the column may
    # already exist when this migration runs.
    if _has_deleted_at():
        return
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if _has_deleted_at():
        op.drop_column("documents", "deleted_at")
