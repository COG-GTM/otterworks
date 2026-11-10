"""Persisted, expiring share links governed by a workspace expiry policy (OTW-74).

Tokens are random (CSPRNG) and stored server-side, so a link can expire and its
expiry can be changed. Links minted before persisted links existed are still
validated by ``ShareLinkService`` and never expire (no retroactive expiry).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.share_link import ShareLink, WorkspaceSharePolicy
from app.services.audit_client import AuditClient, audit_client

MAX_POLICY_DAYS = 365


class ExpiryOutOfBoundsError(ValueError):
    """Requested expiry is outside the workspace's allowed range."""

    def __init__(self, requested: int, minimum: int, maximum: int):
        super().__init__(
            f"Expiry must be between {minimum} and {maximum} days (requested {requested})"
        )


class InvalidPolicyError(ValueError):
    """Workspace policy values are inconsistent."""


class LinkExpiredError(Exception):
    """The share link has already expired."""


@dataclass(frozen=True)
class Policy:
    workspace_id: str
    default_expiry_days: int
    min_expiry_days: int
    max_expiry_days: int
    updated_by: uuid.UUID | None = None
    updated_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "default_expiry_days": self.default_expiry_days,
            "min_expiry_days": self.min_expiry_days,
            "max_expiry_days": self.max_expiry_days,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "updated_at": _aware(self.updated_at).isoformat() if self.updated_at else None,
        }

    def summary(self) -> str:
        return (
            f"default={self.default_expiry_days}d,"
            f"min={self.min_expiry_days}d,max={self.max_expiry_days}d"
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """SQLite drops tzinfo; stored values are always UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def is_expired(link: ShareLink, now: datetime | None = None) -> bool:
    return _aware(link.expires_at) <= (now or _now())


def link_to_dict(link: ShareLink) -> dict:
    return {
        "id": str(link.id),
        "document_id": str(link.document_id),
        "token": link.token,
        "workspace_id": link.workspace_id,
        "created_by": str(link.created_by),
        "created_at": _aware(link.created_at).isoformat(),
        "expires_at": _aware(link.expires_at).isoformat(),
        "expired": is_expired(link),
    }


def validate_policy(default_days: int, min_days: int, max_days: int) -> None:
    if min_days < 1:
        raise InvalidPolicyError("min_expiry_days must be at least 1")
    if max_days > MAX_POLICY_DAYS:
        raise InvalidPolicyError(f"max_expiry_days must be at most {MAX_POLICY_DAYS}")
    if min_days > max_days:
        raise InvalidPolicyError("min_expiry_days must not exceed max_expiry_days")
    if not min_days <= default_days <= max_days:
        raise InvalidPolicyError("default_expiry_days must be between min and max")


class ExpiringShareLinkService:
    def __init__(self, db: AsyncSession, audit: AuditClient | None = None):
        self.db = db
        self.audit = audit or audit_client

    async def get_policy(self, workspace_id: str) -> Policy:
        row = await self.db.get(WorkspaceSharePolicy, workspace_id)
        if row is None:
            return Policy(
                workspace_id=workspace_id,
                default_expiry_days=settings.share_default_expiry_days,
                min_expiry_days=settings.share_min_expiry_days,
                max_expiry_days=settings.share_max_expiry_days,
            )
        return Policy(
            workspace_id=row.workspace_id,
            default_expiry_days=row.default_expiry_days,
            min_expiry_days=row.min_expiry_days,
            max_expiry_days=row.max_expiry_days,
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )

    async def set_policy(
        self,
        workspace_id: str,
        actor_id: uuid.UUID,
        default_days: int,
        min_days: int,
        max_days: int,
    ) -> Policy:
        validate_policy(default_days, min_days, max_days)
        old = await self.get_policy(workspace_id)
        row = await self.db.get(WorkspaceSharePolicy, workspace_id)
        if row is None:
            row = WorkspaceSharePolicy(workspace_id=workspace_id)
            self.db.add(row)
        row.default_expiry_days = default_days
        row.min_expiry_days = min_days
        row.max_expiry_days = max_days
        row.updated_by = actor_id
        row.updated_at = _now()
        await self.db.flush()
        new = await self.get_policy(workspace_id)
        await self._audit_or_rollback(
            actor_id=str(actor_id),
            action="share_policy.updated",
            resource_type="share_policy",
            resource_id=workspace_id,
            workspace_id=workspace_id,
            old_value=old.summary(),
            new_value=new.summary(),
        )
        return new

    def _resolve_days(self, policy: Policy, requested: int | None) -> int:
        days = policy.default_expiry_days if requested is None else requested
        if not policy.min_expiry_days <= days <= policy.max_expiry_days:
            raise ExpiryOutOfBoundsError(days, policy.min_expiry_days, policy.max_expiry_days)
        return days

    async def create(
        self,
        document_id: uuid.UUID,
        workspace_id: str,
        actor_id: uuid.UUID,
        expires_in_days: int | None,
    ) -> ShareLink:
        policy = await self.get_policy(workspace_id)
        days = self._resolve_days(policy, expires_in_days)
        now = _now()
        link = ShareLink(
            id=uuid.uuid4(),
            token=secrets.token_urlsafe(32),
            document_id=document_id,
            workspace_id=workspace_id,
            created_by=actor_id,
            created_at=now,
            expires_at=now + timedelta(days=days),
        )
        self.db.add(link)
        await self.db.flush()
        await self._audit_or_rollback(
            actor_id=str(actor_id),
            action="share_link.created",
            resource_type="share_link",
            resource_id=str(link.id),
            workspace_id=workspace_id,
            old_value=None,
            new_value=_aware(link.expires_at).isoformat(),
        )
        return link

    async def list_for_document(self, document_id: uuid.UUID) -> list[ShareLink]:
        result = await self.db.execute(
            select(ShareLink)
            .where(ShareLink.document_id == document_id)
            .order_by(ShareLink.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_link(self, document_id: uuid.UUID, link_id: uuid.UUID) -> ShareLink | None:
        link = await self.db.get(ShareLink, link_id)
        if link is None or link.document_id != document_id:
            return None
        return link

    async def change_expiry(
        self, link: ShareLink, actor_id: uuid.UUID, expires_in_days: int
    ) -> ShareLink:
        if is_expired(link):
            raise LinkExpiredError()
        policy = await self.get_policy(link.workspace_id)
        days = self._resolve_days(policy, expires_in_days)
        old_value = _aware(link.expires_at).isoformat()
        link.expires_at = _now() + timedelta(days=days)
        await self.db.flush()
        await self._audit_or_rollback(
            actor_id=str(actor_id),
            action="share_link.expiry_changed",
            resource_type="share_link",
            resource_id=str(link.id),
            workspace_id=link.workspace_id,
            old_value=old_value,
            new_value=_aware(link.expires_at).isoformat(),
        )
        return link

    async def find_by_token(self, document_id: uuid.UUID, token: str) -> ShareLink | None:
        result = await self.db.execute(
            select(ShareLink).where(ShareLink.token == token, ShareLink.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def record_expired(self, link: ShareLink) -> None:
        """Audit the first time an expired link is enforced."""
        if link.expired_recorded_at is not None:
            return
        claimed = await self.db.execute(
            update(ShareLink)
            .where(ShareLink.id == link.id, ShareLink.expired_recorded_at.is_(None))
            .values(expired_recorded_at=_now())
        )
        if claimed.rowcount == 0:
            return
        await self._audit_or_rollback(
            actor_id=str(link.created_by),
            action="share_link.expired",
            resource_type="share_link",
            resource_id=str(link.id),
            workspace_id=link.workspace_id,
            old_value="active",
            new_value=f"expired at {_aware(link.expires_at).isoformat()}",
        )

    async def _audit_or_rollback(self, **event: str | None) -> None:
        try:
            await self.audit.record(**event)
        except Exception:
            await self.db.rollback()
            raise
        await self.db.commit()
