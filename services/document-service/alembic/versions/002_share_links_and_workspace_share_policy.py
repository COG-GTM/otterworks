"""Add share_links and workspace_share_policy tables (OTW-43).

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
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False, server_default="folder"),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token", name="uq_share_links_token"),
        sa.CheckConstraint(
            "resource_type IN ('folder')", name="ck_share_links_resource_type"
        ),
    )
    op.create_index("ix_share_links_resource_id", "share_links", ["resource_id"])
    op.create_index("ix_share_links_workspace_id", "share_links", ["workspace_id"])
    op.create_index(
        "ix_share_links_created_by_resource_id",
        "share_links",
        ["created_by", "resource_id"],
    )

    op.create_table(
        "workspace_share_policy",
        sa.Column("workspace_id", sa.Text(), primary_key=True),
        sa.Column("default_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("max_days", sa.Integer(), nullable=False, server_default=sa.text("90")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "1 <= default_days AND default_days <= max_days AND max_days <= 90",
            name="ck_workspace_share_policy_days",
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_share_policy")
    op.drop_index("ix_share_links_created_by_resource_id", table_name="share_links")
    op.drop_index("ix_share_links_workspace_id", table_name="share_links")
    op.drop_index("ix_share_links_resource_id", table_name="share_links")
    op.drop_table("share_links")
