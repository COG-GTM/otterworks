"""Add documents.deleted_at for the document trash.

Revision ID: 002
Revises: 001
Create Date: 2026-09-28 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS: the service adds this column at startup for databases that
    # were created by Base.metadata.create_all() rather than by Alembic.
    op.execute(
        "ALTER TABLE documents "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "UPDATE documents SET deleted_at = updated_at "
        "WHERE is_deleted = true AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS deleted_at")
