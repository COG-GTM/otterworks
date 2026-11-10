"""Folder share links and workspace share policies.

Revision ID: 002_folder_share_links
Revises: 001
Create Date: 2026-11-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "002_folder_share_links"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "folder_share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_audited_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_folder_share_links_token_hash"),
    )
    op.create_index(
        "ix_folder_share_links_folder_id", "folder_share_links", ["folder_id"]
    )

    op.create_table(
        "workspace_share_policies",
        sa.Column("workspace_id", sa.String(64), primary_key=True),
        sa.Column(
            "default_expiry_seconds", sa.Integer(), nullable=False, server_default="2592000"
        ),
        sa.Column("min_expiry_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column(
            "max_expiry_seconds", sa.Integer(), nullable=False, server_default="31536000"
        ),
        sa.Column("allow_never", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_share_policies")
    op.drop_index("ix_folder_share_links_folder_id", table_name="folder_share_links")
    op.drop_table("folder_share_links")
