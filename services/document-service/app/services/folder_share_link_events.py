"""Audit hook for folder share-link lifecycle events.

OTW-69 replaces the body of ``emit_share_link_event`` with emission to
audit-service (shared/events/schemas/audit-events.json). Call sites already
pass everything an audit event needs: actor, workspace, resource, old and new
value; the timestamp is taken at emission.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog

from app.models.folder_share_link import FolderShareLink

logger = structlog.get_logger()


class ShareLinkEventType(StrEnum):
    CREATED = "folder_share_link.created"
    EXPIRY_UPDATED = "folder_share_link.expiry_updated"
    REVOKED = "folder_share_link.revoked"
    EXPIRED = "folder_share_link.expired"


async def emit_share_link_event(
    event_type: ShareLinkEventType,
    link: FolderShareLink,
    actor_id: UUID | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
) -> None:
    """No-op hook (logs only) until OTW-69 wires audit-service. Must never raise."""
    logger.info(
        "folder_share_link_event",
        event_type=str(event_type),
        link_id=str(link.id),
        folder_id=str(link.folder_id),
        workspace_id=link.workspace_id,
        actor_id=str(actor_id) if actor_id else None,
        old_value=old_value,
        new_value=new_value,
    )
