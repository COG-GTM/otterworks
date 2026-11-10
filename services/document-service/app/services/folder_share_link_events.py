"""Audit events for folder share-link lifecycle and sharing policy changes.

Events follow shared/events/schemas/audit-events.json and are published on the
domain SNS topic, whose audit queue the audit-service ``SnsConsumer`` reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog

from app.models.folder_share_link import FolderShareLink
from app.services.event_publisher import event_publisher

logger = structlog.get_logger()

# Namespace for deterministic expiry audit ids (uuid5 of the link id).
EXPIRY_AUDIT_NAMESPACE = uuid.UUID("6f1c4b0e-8c3a-4f39-9a57-1f0d2b7c9e41")


class ShareLinkEventType(StrEnum):
    CREATED = "folder_share_link.created"
    EXPIRY_UPDATED = "folder_share_link.updated"
    REVOKED = "folder_share_link.revoked"
    EXPIRED = "folder_share_link.expired"
    POLICY_CHANGED = "folder_share_link.policy_changed"


def expiry_audit_id(link_id: UUID) -> UUID:
    """Stable audit id for a link's expiry, so a re-delivered expiry event overwrites."""
    return uuid.uuid5(EXPIRY_AUDIT_NAMESPACE, f"{link_id}:expired")


def _iso(value: datetime) -> str:
    value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def build_share_link_event(
    event_type: ShareLinkEventType,
    link: FolderShareLink,
    actor_id: UUID | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    *,
    audit_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "eventType": str(event_type),
        "auditId": str(audit_id or uuid.uuid4()),
        "actor": {
            "type": "user" if actor_id else "system",
            "id": str(actor_id) if actor_id else None,
        },
        "workspaceId": link.workspace_id,
        "resource": {
            "type": "folder_share_link",
            "folderId": str(link.folder_id),
            "linkId": str(link.id),
        },
        "oldValue": old_value,
        "newValue": new_value,
        "timestamp": _iso(occurred_at or datetime.now(UTC)),
    }


async def emit_share_link_event(
    event_type: ShareLinkEventType,
    link: FolderShareLink,
    actor_id: UUID | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    *,
    audit_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> bool:
    """Publish one audit event. Never raises; returns False if delivery failed."""
    try:
        event = build_share_link_event(
            event_type,
            link,
            actor_id,
            old_value,
            new_value,
            audit_id=audit_id,
            occurred_at=occurred_at,
        )
        delivered = await event_publisher.publish(str(event_type), event)
    except Exception:
        logger.exception("folder_share_link_event_failed", event_type=str(event_type))
        return False
    logger.info(
        "folder_share_link_event",
        event_type=str(event_type),
        audit_id=event["auditId"],
        link_id=str(link.id),
        folder_id=str(link.folder_id),
        delivered=delivered,
    )
    return delivered
