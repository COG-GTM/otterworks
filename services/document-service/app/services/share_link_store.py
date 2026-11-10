"""Persisted, expiring share links and workspace share policies (OTW-53).

Links minted before OTW-53 are stateless (see ``share_link.ShareLinkService``)
and keep working without an expiry: policies are never applied retroactively.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sharing import DEFAULT_WORKSPACE_ID, ShareLink, WorkspaceSharePolicy
from app.services.audit_client import AuditClient, audit_client

NEVER = "never"


class ExpiryPolicyError(ValueError):
    """Requested expiry is outside the workspace policy."""


@dataclass
class PolicyValues:
    default_expiry_days: int | None = None
    min_expiry_days: int = 1
    max_expiry_days: int | None = None
    allow_no_expiry: bool = True

    def describe(self) -> str:
        return (
            f"default={self.default_expiry_days or NEVER};"
            f"min={self.min_expiry_days};"
            f"max={self.max_expiry_days or NEVER};"
            f"allow_no_expiry={str(self.allow_no_expiry).lower()}"
        )


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _fmt(value: datetime | None) -> str:
    value = as_aware(value)
    return value.isoformat() if value else NEVER


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def validate_policy(values: PolicyValues) -> None:
    if values.min_expiry_days < 1:
        raise ExpiryPolicyError("min_expiry_days must be at least 1")
    if values.max_expiry_days is not None and values.max_expiry_days < values.min_expiry_days:
        raise ExpiryPolicyError("max_expiry_days must be >= min_expiry_days")
    if values.default_expiry_days is None:
        if not values.allow_no_expiry:
            raise ExpiryPolicyError(
                "default_expiry_days is required when links must expire"
            )
        return
    if values.default_expiry_days < values.min_expiry_days or (
        values.max_expiry_days is not None
        and values.default_expiry_days > values.max_expiry_days
    ):
        raise ExpiryPolicyError("default_expiry_days must be within min/max bounds")


def resolve_expiry(
    policy: PolicyValues,
    now: datetime,
    expires_in_days: int | None,
    no_expiry: bool,
) -> datetime | None:
    """Return expires_at for a link, applying the default and enforcing bounds."""
    if no_expiry:
        if not policy.allow_no_expiry:
            raise ExpiryPolicyError("This workspace requires share links to expire")
        return None
    if expires_in_days is None:
        if policy.default_expiry_days is None:
            return None
        return now + timedelta(days=policy.default_expiry_days)
    if expires_in_days < policy.min_expiry_days:
        raise ExpiryPolicyError(
            f"Expiry must be at least {policy.min_expiry_days} day(s)"
        )
    if policy.max_expiry_days is not None and expires_in_days > policy.max_expiry_days:
        raise ExpiryPolicyError(
            f"Expiry must be at most {policy.max_expiry_days} day(s)"
        )
    return now + timedelta(days=expires_in_days)


def is_expired(link: ShareLink, now: datetime | None = None) -> bool:
    expires_at = as_aware(link.expires_at)
    return expires_at is not None and (now or utcnow()) >= expires_at


class ShareLinkStore:
    def __init__(self, db: AsyncSession, audit: AuditClient | None = None) -> None:
        self.db = db
        self.audit = audit or audit_client

    async def get_policy(self, workspace_id: str = DEFAULT_WORKSPACE_ID) -> PolicyValues:
        row = await self.db.get(WorkspaceSharePolicy, workspace_id)
        if row is None:
            return PolicyValues()
        return PolicyValues(
            default_expiry_days=row.default_expiry_days,
            min_expiry_days=row.min_expiry_days,
            max_expiry_days=row.max_expiry_days,
            allow_no_expiry=row.allow_no_expiry,
        )

    async def update_policy(
        self, workspace_id: str, values: PolicyValues, actor_id: uuid.UUID
    ) -> PolicyValues:
        validate_policy(values)
        old = await self.get_policy(workspace_id)
        row = await self.db.get(WorkspaceSharePolicy, workspace_id)
        if row is None:
            row = WorkspaceSharePolicy(workspace_id=workspace_id)
            self.db.add(row)
        row.default_expiry_days = values.default_expiry_days
        row.min_expiry_days = values.min_expiry_days
        row.max_expiry_days = values.max_expiry_days
        row.allow_no_expiry = values.allow_no_expiry
        row.updated_by = actor_id
        await self.db.commit()
        if old != values:
            await self.audit.record(
                event="share_policy.changed",
                actor_id=str(actor_id),
                workspace_id=workspace_id,
                resource_type="workspace",
                resource_id=workspace_id,
                old_value=old.describe(),
                new_value=values.describe(),
            )
        return values

    async def create_link(
        self,
        document_id: uuid.UUID,
        actor_id: uuid.UUID,
        expires_in_days: int | None = None,
        no_expiry: bool = False,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> ShareLink:
        policy = await self.get_policy(workspace_id)
        now = utcnow()
        expires_at = resolve_expiry(policy, now, expires_in_days, no_expiry)
        link = ShareLink(
            document_id=document_id,
            workspace_id=workspace_id,
            token=generate_token(),
            created_by=actor_id,
            created_at=now,
            expires_at=expires_at,
        )
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        await self.audit.record(
            event="share_link.created",
            actor_id=str(actor_id),
            workspace_id=workspace_id,
            resource_type="document",
            resource_id=str(document_id),
            old_value=None,
            new_value=_fmt(expires_at),
            extra={"share_link_id": str(link.id)},
        )
        return link

    async def list_links(self, document_id: uuid.UUID) -> list[ShareLink]:
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
        self,
        link: ShareLink,
        actor_id: uuid.UUID,
        expires_in_days: int | None = None,
        no_expiry: bool = False,
    ) -> ShareLink:
        if is_expired(link):
            raise ExpiryPolicyError("Expired links cannot be extended; create a new link")
        policy = await self.get_policy(link.workspace_id)
        old_expires_at = as_aware(link.expires_at)
        new_expires_at = resolve_expiry(policy, utcnow(), expires_in_days, no_expiry)
        link.expires_at = new_expires_at
        await self.db.commit()
        await self.db.refresh(link)
        if old_expires_at != new_expires_at:
            await self.audit.record(
                event="share_link.expiry_changed",
                actor_id=str(actor_id),
                workspace_id=link.workspace_id,
                resource_type="document",
                resource_id=str(link.document_id),
                old_value=_fmt(old_expires_at),
                new_value=_fmt(new_expires_at),
                extra={"share_link_id": str(link.id)},
            )
        return link

    async def find_by_token(self, document_id: uuid.UUID, token: str) -> ShareLink | None:
        result = await self.db.execute(
            select(ShareLink).where(
                ShareLink.token == token, ShareLink.document_id == document_id
            )
        )
        return result.scalar_one_or_none()

    async def mark_expired(self, link: ShareLink) -> bool:
        """Emit the one-time ``share_link.expired`` audit event for a link.

        The link is only marked audited once delivery succeeds, so the sweep
        retries events that audit-service did not accept.
        """
        if link.expiry_audited or not is_expired(link):
            return False
        delivered = await self.audit.record(
            event="share_link.expired",
            actor_id="system",
            workspace_id=link.workspace_id,
            resource_type="document",
            resource_id=str(link.document_id),
            old_value="active",
            new_value=f"expired at {_fmt(link.expires_at)}",
            extra={"share_link_id": str(link.id)},
        )
        if not delivered:
            return False
        link.expiry_audited = True
        await self.db.commit()
        return True

    async def sweep_expired(self) -> int:
        result = await self.db.execute(
            select(ShareLink).where(
                ShareLink.expiry_audited.is_(False),
                ShareLink.expires_at.is_not(None),
                ShareLink.expires_at <= utcnow(),
            )
        )
        count = 0
        for link in result.scalars().all():
            if await self.mark_expired(link):
                count += 1
        return count
