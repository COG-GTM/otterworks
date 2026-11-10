"""Persisted, expiring share links and the workspace share policy (OTW-20).

New links carry a random token (CSPRNG) and an expiry. Links minted before
OTW-20 are stateless and still validated by ShareLinkService; policies never
apply to them retroactively.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.models.share_link import ShareLink, ShareLinkRollout, WorkspaceSharePolicy
from app.services.event_publisher import event_publisher

MAX_EXPIRY_DAYS = 365


class ShareLinkExpiredError(Exception):
    pass


class ExpiryOutOfBoundsError(ValueError):
    pass


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def is_expired(link: ShareLink, now: datetime | None = None) -> bool:
    return _as_utc(link.expires_at) <= (now or datetime.now(UTC))


def validate_policy(default_days: int, min_days: int, max_days: int) -> None:
    if not 1 <= min_days <= max_days <= MAX_EXPIRY_DAYS:
        raise ExpiryOutOfBoundsError(
            f"Bounds must satisfy 1 <= minimum <= maximum <= {MAX_EXPIRY_DAYS} days"
        )
    if not min_days <= default_days <= max_days:
        raise ExpiryOutOfBoundsError(
            f"Default expiry must be between {min_days} and {max_days} days"
        )


class ShareLinkStore:
    """Persisted share links and the workspace share policy."""

    def __init__(self, db: AsyncSession, workspace_id: str | None = None):
        self.db = db
        self.workspace_id = workspace_id or settings.workspace_id

    async def get_policy(self) -> WorkspaceSharePolicy:
        policy = await self.db.get(WorkspaceSharePolicy, self.workspace_id)
        if policy is None:
            policy = WorkspaceSharePolicy(
                workspace_id=self.workspace_id,
                default_expiry_days=settings.share_link_default_expiry_days,
                min_expiry_days=settings.share_link_min_expiry_days,
                max_expiry_days=settings.share_link_max_expiry_days,
            )
        return policy

    async def update_policy(
        self, actor_id: uuid.UUID, default_days: int, min_days: int, max_days: int
    ) -> WorkspaceSharePolicy:
        validate_policy(default_days, min_days, max_days)
        policy = await self.get_policy()
        old = _policy_value(policy)
        policy.default_expiry_days = default_days
        policy.min_expiry_days = min_days
        policy.max_expiry_days = max_days
        policy.updated_by = actor_id
        policy.updated_at = datetime.now(UTC)
        self.db.add(policy)
        await self.db.commit()
        await self._audit(
            "share_policy_update", "workspace", self.workspace_id, actor_id,
            old_value=old, new_value=_policy_value(policy),
        )
        return policy

    async def _resolve_days(self, expires_in_days: int | None) -> int:
        policy = await self.get_policy()
        days = policy.default_expiry_days if expires_in_days is None else expires_in_days
        if not policy.min_expiry_days <= days <= policy.max_expiry_days:
            raise ExpiryOutOfBoundsError(
                f"Expiry must be between {policy.min_expiry_days} and "
                f"{policy.max_expiry_days} days"
            )
        return days

    async def create_link(
        self, document_id: uuid.UUID, actor_id: uuid.UUID, expires_in_days: int | None
    ) -> ShareLink:
        days = await self._resolve_days(expires_in_days)
        now = datetime.now(UTC)
        link = ShareLink(
            token=secrets.token_urlsafe(32),
            document_id=document_id,
            created_by=actor_id,
            created_at=now,
            expires_at=now + timedelta(days=days),
        )
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        await self._audit(
            "share_link_create", "share_link", str(link.id), actor_id,
            old_value="", new_value=_as_utc(link.expires_at).isoformat(),
            document_id=str(document_id),
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

    async def update_expiry(
        self, link: ShareLink, actor_id: uuid.UUID, expires_in_days: int
    ) -> ShareLink:
        if is_expired(link):
            raise ShareLinkExpiredError
        days = await self._resolve_days(expires_in_days)
        old = _as_utc(link.expires_at).isoformat()
        link.expires_at = datetime.now(UTC) + timedelta(days=days)
        await self.db.commit()
        await self.db.refresh(link)
        await self._audit(
            "share_link_expiry_change", "share_link", str(link.id), actor_id,
            old_value=old, new_value=_as_utc(link.expires_at).isoformat(),
            document_id=str(link.document_id),
        )
        return link

    async def find_by_token(self, document_id: uuid.UUID, token: str) -> ShareLink | None:
        result = await self.db.execute(
            select(ShareLink).where(
                ShareLink.token == token, ShareLink.document_id == document_id
            )
        )
        return result.scalar_one_or_none()

    async def sweep_expired(self) -> int:
        """Audit every link that has expired but whose expiry is not yet recorded."""
        result = await self.db.execute(
            select(ShareLink).where(
                ShareLink.expiry_audited.is_(False),
                ShareLink.expires_at <= datetime.now(UTC),
            )
        )
        links = list(result.scalars().all())
        for link in links:
            await self.record_expiry(link)
        return len(links)

    async def is_legacy_shareable(self, document: Document) -> bool:
        """Stateless links exist only for documents created before expiring links shipped."""
        cutoff = settings.share_link_legacy_cutoff
        if cutoff is None:
            rollout = await self.db.get(ShareLinkRollout, 1)
            cutoff = rollout.legacy_cutoff if rollout else None
        if cutoff is None:
            cutoff = await self.db.scalar(select(func.min(ShareLink.created_at)))
        return cutoff is None or _as_utc(document.created_at) < _as_utc(cutoff)

    async def record_rollout(self) -> None:
        """Pin the legacy cutoff the first time a release with expiring links starts."""
        if await self.db.get(ShareLinkRollout, 1) is not None:
            return
        first_link = await self.db.scalar(select(func.min(ShareLink.created_at)))
        self.db.add(ShareLinkRollout(id=1, legacy_cutoff=first_link or datetime.now(UTC)))
        try:
            await self.db.commit()
        except IntegrityError:
            # Another replica recorded the rollout first; its cutoff stands.
            await self.db.rollback()

    async def record_expiry(self, link: ShareLink) -> None:
        """Audit a link's expiry exactly once, even when a request and the sweep race."""
        claimed = await self.db.execute(
            update(ShareLink)
            .where(ShareLink.id == link.id, ShareLink.expiry_audited.is_(False))
            .values(expiry_audited=True)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if claimed.rowcount != 1:
            return
        await self._audit(
            "share_link_expire", "share_link", str(link.id), None,
            old_value="active", new_value="expired",
            document_id=str(link.document_id),
            expires_at=_as_utc(link.expires_at).isoformat(),
        )

    async def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        actor_id: uuid.UUID | None,
        *,
        old_value: str,
        new_value: str,
        **extra: str,
    ) -> None:
        await event_publisher.publish_audit(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=str(actor_id) if actor_id else "system",
            details={
                "workspace": self.workspace_id,
                "oldValue": old_value,
                "newValue": new_value,
                **extra,
            },
        )


def _policy_value(policy: WorkspaceSharePolicy) -> str:
    return (
        f"default={policy.default_expiry_days}d;"
        f"min={policy.min_expiry_days}d;max={policy.max_expiry_days}d"
    )
