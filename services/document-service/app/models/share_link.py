"""Share link and workspace share policy models."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiry_audited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WorkspaceSharePolicy(Base):
    __tablename__ = "workspace_share_policies"

    workspace_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    default_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False)
    min_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class ShareLinkRollout(Base):
    """Single row recording when expiring links shipped; older documents keep stateless links."""

    __tablename__ = "share_link_rollout"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    legacy_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
