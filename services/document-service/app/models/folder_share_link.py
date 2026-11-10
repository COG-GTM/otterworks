"""Folder share-link SQLAlchemy model.

A folder share link is a persisted, expiring, revocable record. Only an HMAC of
the raw token is stored (see ``app.services.folder_share_token``); the raw token
is handed to the caller once, at creation time. Revoked and expired links keep
their record for the audit trail.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DEFAULT_WORKSPACE_ID = "default"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; every timestamp in this table is stored in UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class FolderShareLinkStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class FolderShareLink(Base):
    __tablename__ = "folder_share_links"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_folder_share_links_token_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=DEFAULT_WORKSPACE_ID,
        server_default=DEFAULT_WORKSPACE_ID,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expiry_audited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def status_at(self, now: datetime | None = None) -> FolderShareLinkStatus:
        """Link status at ``now``; revocation wins over expiry."""
        now = _as_utc(now) if now is not None else _utcnow()
        if self.revoked_at is not None and _as_utc(self.revoked_at) <= now:
            return FolderShareLinkStatus.REVOKED
        if _as_utc(self.expires_at) <= now:
            return FolderShareLinkStatus.EXPIRED
        return FolderShareLinkStatus.ACTIVE

    @property
    def status(self) -> FolderShareLinkStatus:
        return self.status_at()
