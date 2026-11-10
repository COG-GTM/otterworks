"""Scheduled sweep that records exactly one expiry audit event per folder share link.

A link is swept once ``expires_at`` has passed, unless it was revoked before it
expired (that link never expired as an active link; its revocation is already
audited). ``expiry_audited_at`` is set only after the event was delivered, so a
failed publish is retried on the next run. Rows are claimed with
``FOR UPDATE SKIP LOCKED`` so concurrent replicas never sweep the same link, and
the event's ``auditId`` is derived from the link id so a re-delivery after a
crash overwrites the same audit record instead of adding a second one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.folder_share_link import FolderShareLink, FolderShareLinkStatus
from app.services.folder_share_link_events import (
    ShareLinkEventType,
    emit_share_link_event,
    expiry_audit_id,
)
from app.services.folder_share_link_service import as_utc, utcnow

logger = structlog.get_logger()


def _due_for_expiry_audit(now: datetime, batch_size: int):  # noqa: ANN202
    return (
        select(FolderShareLink)
        .where(
            FolderShareLink.expires_at <= now,
            FolderShareLink.expiry_audited_at.is_(None),
            or_(
                FolderShareLink.revoked_at.is_(None),
                FolderShareLink.revoked_at > FolderShareLink.expires_at,
            ),
        )
        .order_by(FolderShareLink.expires_at, FolderShareLink.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )


async def sweep_expired_links(
    db: AsyncSession, now: datetime | None = None, batch_size: int = 100
) -> int:
    """Emit expiry events for links that expired since the last run; returns how many."""
    now = now or utcnow()
    emitted = 0
    while True:
        links = list((await db.execute(_due_for_expiry_audit(now, batch_size))).scalars())
        if not links:
            break
        failed = 0
        for link in links:
            expires_at = as_utc(link.expires_at).isoformat()
            delivered = await emit_share_link_event(
                ShareLinkEventType.EXPIRED,
                link,
                None,
                {"status": FolderShareLinkStatus.ACTIVE.value, "expires_at": expires_at},
                {"status": FolderShareLinkStatus.EXPIRED.value, "expires_at": expires_at},
                audit_id=expiry_audit_id(link.id),
                occurred_at=as_utc(link.expires_at),
            )
            if delivered:
                link.expiry_audited_at = now
                emitted += 1
            else:
                failed += 1
        await db.commit()
        if failed or len(links) < batch_size:
            if failed:
                logger.warning("folder_share_link_expiry_sweep_publish_failed", failed=failed)
            break
    if emitted:
        logger.info("folder_share_link_expiry_sweep", emitted=emitted)
    return emitted


async def run_expiry_sweep_loop(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    interval_seconds: float,
    batch_size: int = 100,
) -> None:
    """Run the sweep every ``interval_seconds`` until cancelled. Errors are logged, not raised."""
    while True:
        try:
            async with session_factory() as db:
                await sweep_expired_links(db, batch_size=batch_size)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("folder_share_link_expiry_sweep_failed")
        await asyncio.sleep(interval_seconds)
