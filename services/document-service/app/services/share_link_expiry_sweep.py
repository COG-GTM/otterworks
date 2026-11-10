"""Periodic sweep that records expiry of folder share links past ``expires_at`` (OTW-46).

It only sets ``expired_at`` (via ShareLinkRepository.mark_expired) and never touches
``expires_at``, so a link is never extended. ``share_link_expired`` is emitted only when
mark_expired returns True, so the sweep and resolve together emit it exactly once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_events import as_utc
from app.services.share_link_events import SHARE_LINK_EXPIRED, emit_share_link_event
from app.services.share_link_repository import ShareLinkRepository

logger = structlog.get_logger()


async def sweep_expired_share_links(
    db: AsyncSession, *, now: datetime | None = None, batch_size: int = 500
) -> int:
    """Mark links past expiry and emit one event per newly marked link. Returns the count."""
    now = now or datetime.now(UTC)
    repo = ShareLinkRepository(db)
    marked = 0
    for link in await repo.list_unmarked_expired(now, limit=batch_size):
        if await repo.mark_expired(link, now):
            marked += 1
            await emit_share_link_event(
                SHARE_LINK_EXPIRED,
                link,
                actor=None,
                old_value={"expires_at": as_utc(link.expires_at).isoformat()},
                new_value={"expired_at": now.isoformat()},
                occurred_at=now,
            )
    if marked:
        logger.info("share_link_expiry_sweep", marked=marked)
    return marked


async def run_expiry_sweep_loop(
    session_factory: Callable[[], AsyncSession], interval_seconds: float
) -> None:
    """Sweep every ``interval_seconds`` until cancelled; a failed run is logged and retried."""
    while True:
        try:
            async with session_factory() as db:
                await sweep_expired_share_links(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("share_link_expiry_sweep_failed")
        await asyncio.sleep(interval_seconds)
