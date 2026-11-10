"""Folder share link and workspace share-policy SQLAlchemy models."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MIN_SHARE_DAYS = 1
DEFAULT_SHARE_DAYS = 30
MAX_SHARE_DAYS = 90

RESOURCE_TYPE_FOLDER = "folder"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ShareLink(Base):
    """An expiring, read-only share link for a resource (currently folders only)."""

    __tablename__ = "share_links"
    __table_args__ = (
        CheckConstraint(
            f"resource_type IN ('{RESOURCE_TYPE_FOLDER}')",
            name="ck_share_links_resource_type",
        ),
        Index("ix_share_links_created_by_resource_id", "created_by", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    resource_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=RESOURCE_TYPE_FOLDER,
        server_default=text(f"'{RESOURCE_TYPE_FOLDER}'"),
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkspaceSharePolicy(Base):
    """Per-workspace link expiry policy. A missing row means 30/90 days."""

    __tablename__ = "workspace_share_policy"
    __table_args__ = (
        CheckConstraint(
            f"{MIN_SHARE_DAYS} <= default_days AND default_days <= max_days "
            f"AND max_days <= {MAX_SHARE_DAYS}",
            name="ck_workspace_share_policy_days",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(Text, primary_key=True)
    default_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_SHARE_DAYS,
        server_default=text(str(DEFAULT_SHARE_DAYS)),
    )
    max_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=MAX_SHARE_DAYS,
        server_default=text(str(MAX_SHARE_DAYS)),
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )
