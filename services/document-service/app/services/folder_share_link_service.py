"""Persistence and lifecycle rules for folder share links."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.folder_share_link import DEFAULT_WORKSPACE_ID, FolderShareLink
from app.services.folder_share_token import hash_token, new_token


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; every timestamp in this table is stored in UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class FolderShareLinkService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, folder_id: UUID, created_by: UUID, expires_in_days: int
    ) -> tuple[FolderShareLink, str]:
        """Persist a new link and return it with the raw token (never stored)."""
        token, token_hash = new_token()
        created_at = utcnow()
        link = FolderShareLink(
            folder_id=folder_id,
            workspace_id=DEFAULT_WORKSPACE_ID,
            token_hash=token_hash,
            created_by=created_by,
            created_at=created_at,
            expires_at=created_at + timedelta(days=expires_in_days),
        )
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        return link, token

    async def list_for_folder(self, folder_id: UUID) -> list[FolderShareLink]:
        result = await self.db.execute(
            select(FolderShareLink)
            .where(FolderShareLink.folder_id == folder_id)
            .order_by(FolderShareLink.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, link_id: UUID, *, for_update: bool = False) -> FolderShareLink | None:
        stmt = select(FolderShareLink).where(FolderShareLink.id == link_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_token(self, token: str) -> FolderShareLink | None:
        result = await self.db.execute(
            select(FolderShareLink).where(FolderShareLink.token_hash == hash_token(token))
        )
        return result.scalar_one_or_none()

    async def set_expiry(self, link: FolderShareLink, expires_at: datetime) -> FolderShareLink:
        link.expires_at = expires_at
        await self.db.commit()
        await self.db.refresh(link)
        return link

    async def revoke(self, link: FolderShareLink, at: datetime) -> FolderShareLink:
        link.revoked_at = at
        await self.db.commit()
        await self.db.refresh(link)
        return link
