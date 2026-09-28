"""Record when a document was soft-deleted.

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


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE documents SET deleted_at = updated_at WHERE is_deleted = true"
    )
    op.create_index(
        "ix_documents_is_deleted_deleted_at",
        "documents",
        ["is_deleted", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_is_deleted_deleted_at", table_name="documents")
    op.drop_column("documents", "deleted_at")
