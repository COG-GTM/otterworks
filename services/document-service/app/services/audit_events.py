"""Audit events for OTW-41 share links, published to audit-service via SNS.

Payload keys follow shared/events/schemas/audit-events.json and are the snake_case keys
audit-service's SnsConsumer.MapAuditEventMessage reads from ``payload``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from app.services.event_publisher import event_publisher

logger = structlog.get_logger()

SYSTEM_ACTOR = "system"

AUDIT_PAYLOAD_KEYS = frozenset(
    {
        "user_id",
        "action",
        "resource_type",
        "resource_id",
        "workspace_id",
        "old_value",
        "new_value",
        "timestamp",
        "details",
    }
)


def as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo; every stored timestamp is UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def build_audit_payload(
    action: str,
    *,
    actor: UUID | str | None,
    workspace_id: str,
    resource_type: str,
    resource_id: UUID | str,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    occurred_at: datetime,
    details: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "user_id": str(actor) if actor is not None else SYSTEM_ACTOR,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "workspace_id": workspace_id,
        "old_value": old_value,
        "new_value": new_value,
        "timestamp": as_utc(occurred_at).isoformat(),
        "details": details or {},
    }


async def publish_audit_event(action: str, payload: dict[str, Any]) -> None:
    """Publish without ever failing the caller's request."""
    try:
        await event_publisher.publish(action, payload)
    except Exception:
        logger.exception("audit_event_publish_failed", event_type=action)
