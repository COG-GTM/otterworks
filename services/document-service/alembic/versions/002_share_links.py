"""Persisted share links and workspace share policies (OTW-53).

Revision ID: 002
Revises: 001
Create Date: 2026-11-10 00:00:00.000000

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
    op.create_table(
        "share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("workspace_id", sa.String(100), nullable=False, server_default="default"),
        sa.Column("token", sa.String(128), nullable=False, unique=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("expiry_audited", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "workspace_share_policies",
        sa.Column("workspace_id", sa.String(100), primary_key=True),
        sa.Column("default_expiry_days", sa.Integer(), nullable=True),
        sa.Column("min_expiry_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_expiry_days", sa.Integer(), nullable=True),
        sa.Column("allow_no_expiry", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_share_policies")
    op.drop_table("share_links")
