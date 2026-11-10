"""Single hook point for folder share-link audit events (OTW-46).

Events are sent to audit-service using shared/events/schemas/audit-events.json.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.models.share_link import ShareLink
from app.services.audit_events import build_audit_payload, publish_audit_event

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
    payload = build_audit_payload(
        event_type,
        actor=actor,
        workspace_id=link.workspace_id,
        resource_type=link.resource_type,
        resource_id=link.resource_id,
        old_value=old_value,
        new_value=new_value,
        occurred_at=occurred_at,
        details={"share_link_id": str(link.id)},
    )
    await publish_audit_event(event_type, payload)
