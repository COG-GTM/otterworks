"""Single hook point for folder share-link audit events.

OTW-46 fills this in to send events to audit-service using
shared/events/schemas/audit-events.json. Until then it is a no-op.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.models.share_link import ShareLink

SHARE_LINK_CREATED = "share_link_created"
SHARE_LINK_EXPIRY_CHANGED = "share_link_expiry_changed"
SHARE_LINK_EXPIRED = "share_link_expired"


async def emit_share_link_event(
    event_type: str,
    link: ShareLink,
    *,
    actor: UUID | None,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    occurred_at: datetime,
) -> None:
    """Record a share-link lifecycle event. ``actor`` is None for system-detected expiry."""
    return None
