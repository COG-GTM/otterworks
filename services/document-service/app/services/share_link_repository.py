"""Persistence for folder share links and workspace share policies (OTW-41)."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.share_link import (
    DEFAULT_SHARE_DAYS,
    MAX_SHARE_DAYS,
    MIN_SHARE_DAYS,
    RESOURCE_TYPE_FOLDER,
    ShareLink,
    WorkspaceSharePolicy,
)

TOKEN_BYTES = 32


def generate_share_token() -> str:
    """Return a new unguessable share token from the OS CSPRNG."""
    return secrets.token_urlsafe(TOKEN_BYTES)


class InvalidSharePolicyError(ValueError):
    """Raised when a share policy violates 1 <= default_days <= max_days <= 90."""


def validate_share_policy(default_days: int, max_days: int) -> None:
    if not (MIN_SHARE_DAYS <= default_days <= max_days <= MAX_SHARE_DAYS):
        raise InvalidSharePolicyError(
            f"Require {MIN_SHARE_DAYS} <= default_days <= max_days <= {MAX_SHARE_DAYS}; "
            f"got default_days={default_days}, max_days={max_days}"
        )


@dataclass(frozen=True)
class EffectiveSharePolicy:
    """The policy in force for a workspace; ``updated_at`` is None for the built-in default."""

    workspace_id: str
    default_days: int
    max_days: int
    updated_by: uuid.UUID | None = None
    updated_at: datetime | None = None

    @classmethod
    def builtin(cls, workspace_id: str) -> EffectiveSharePolicy:
        return cls(
            workspace_id=workspace_id,
            default_days=DEFAULT_SHARE_DAYS,
            max_days=MAX_SHARE_DAYS,
        )

    @classmethod
    def from_row(cls, row: WorkspaceSharePolicy) -> EffectiveSharePolicy:
        return cls(
            workspace_id=row.workspace_id,
            default_days=row.default_days,
            max_days=row.max_days,
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )


class ShareLinkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        resource_id: uuid.UUID,
        workspace_id: str,
        created_by: uuid.UUID,
        expires_at: datetime,
        resource_type: str = RESOURCE_TYPE_FOLDER,
        token: str | None = None,
    ) -> ShareLink:
        link = ShareLink(
            token=token or generate_share_token(),
            resource_type=resource_type,
            resource_id=resource_id,
            workspace_id=workspace_id,
            created_by=created_by,
            expires_at=expires_at,
        )
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        return link

    async def get(self, link_id: uuid.UUID) -> ShareLink | None:
        return await self.db.get(ShareLink, link_id)

    async def get_by_token(self, token: str) -> ShareLink | None:
        result = await self.db.execute(select(ShareLink).where(ShareLink.token == token))
        return result.scalar_one_or_none()

    async def list_for_resource(
        self, resource_id: uuid.UUID, *, created_by: uuid.UUID | None = None
    ) -> list[ShareLink]:
        query = select(ShareLink).where(ShareLink.resource_id == resource_id)
        if created_by is not None:
            query = query.where(ShareLink.created_by == created_by)
        result = await self.db.execute(query.order_by(ShareLink.created_at.desc()))
        return list(result.scalars().all())

    async def update_expiry(self, link: ShareLink, expires_at: datetime) -> ShareLink:
        link.expires_at = expires_at
        await self.db.commit()
        await self.db.refresh(link)
        return link

    async def list_unmarked_expired(self, now: datetime, *, limit: int) -> list[ShareLink]:
        """Links past ``expires_at`` whose expiry has not been recorded yet, oldest first."""
        result = await self.db.execute(
            select(ShareLink)
            .where(ShareLink.expires_at <= now, ShareLink.expired_at.is_(None))
            .order_by(ShareLink.expires_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_expired(self, link: ShareLink, expired_at: datetime) -> bool:
        """Record when expiry was first detected. Returns False if already recorded or if
        the link was extended past ``expired_at`` since it was loaded."""
        if link.expired_at is not None:
            return False
        result = await self.db.execute(
            update(ShareLink)
            .where(
                ShareLink.id == link.id,
                ShareLink.expired_at.is_(None),
                ShareLink.expires_at <= expired_at,
            )
            .values(expired_at=expired_at)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        await self.db.refresh(link)
        return result.rowcount == 1


class WorkspaceSharePolicyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, workspace_id: str) -> EffectiveSharePolicy:
        row = await self.db.get(WorkspaceSharePolicy, workspace_id)
        if row is None:
            return EffectiveSharePolicy.builtin(workspace_id)
        return EffectiveSharePolicy.from_row(row)

    async def upsert(
        self,
        workspace_id: str,
        *,
        default_days: int,
        max_days: int,
        updated_by: uuid.UUID | None,
    ) -> EffectiveSharePolicy:
        validate_share_policy(default_days, max_days)
        values = {
            "default_days": default_days,
            "max_days": max_days,
            "updated_by": updated_by,
            "updated_at": datetime.now(UTC),
        }
        dialect = self.db.get_bind().dialect.name
        insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
        stmt = (
            insert(WorkspaceSharePolicy)
            .values(workspace_id=workspace_id, **values)
            .on_conflict_do_update(index_elements=["workspace_id"], set_=values)
        )
        await self.db.execute(stmt)
        await self.db.commit()
        row = await self.db.get(WorkspaceSharePolicy, workspace_id, populate_existing=True)
        return EffectiveSharePolicy.from_row(row)
