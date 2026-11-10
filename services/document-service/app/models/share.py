"""Folder share link and workspace share policy SQLAlchemy models (OTW-29)."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Boolean, DateTime, Integer, String, false, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DEFAULT_EXPIRY_SECONDS = 30 * 24 * 3600
MIN_EXPIRY_SECONDS = 3600
MAX_EXPIRY_SECONDS = 365 * 24 * 3600
DEFAULT_ALLOW_NEVER = False

ShareLinkStatus = Literal["active", "expired", "revoked"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class FolderShareLink(Base):
    __tablename__ = "folder_share_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_audited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def status_at(self, now: datetime | None = None) -> ShareLinkStatus:
        """Revoked wins over expired; a NULL ``expires_at`` never expires."""
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and _as_aware(self.expires_at) <= (now or _utcnow()):
            return "expired"
        return "active"


class WorkspaceSharePolicy(Base):
    __tablename__ = "workspace_share_policies"

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    default_expiry_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_EXPIRY_SECONDS,
        server_default=str(DEFAULT_EXPIRY_SECONDS),
    )
    min_expiry_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=MIN_EXPIRY_SECONDS, server_default=str(MIN_EXPIRY_SECONDS)
    )
    max_expiry_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=MAX_EXPIRY_SECONDS, server_default=str(MAX_EXPIRY_SECONDS)
    )
    allow_never: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=DEFAULT_ALLOW_NEVER, server_default=false()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )
