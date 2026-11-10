"""Audit publisher for folder share link and share policy events (OTW-29).

Ships as a no-op that only logs; OTW-34 replaces ``emit`` with real publishing
to audit-service.
"""

from typing import Literal

import structlog

logger = structlog.get_logger()

ShareAuditEventType = Literal[
    "share_link_created",
    "share_link_updated",
    "share_link_revoked",
    "share_link_expired",
    "share_policy_updated",
]
ShareAuditResourceType = Literal["share_link", "share_policy"]

SHARE_AUDIT_EVENT_TYPES: frozenset[str] = frozenset(ShareAuditEventType.__args__)
SHARE_AUDIT_RESOURCE_TYPES: frozenset[str] = frozenset(ShareAuditResourceType.__args__)


class ShareAuditPublisher:
    """Emits audit events for share links and workspace share policies."""

    async def emit(
        self,
        event_type: str,
        actor_id: str | None,
        workspace_id: str,
        resource_type: str,
        resource_id: str,
        old_value: dict | None,
        new_value: dict | None,
    ) -> None:
        logger.info(
            "share_audit_event",
            event_type=event_type,
            actor_id=actor_id,
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
            old_value=old_value,
            new_value=new_value,
        )


share_audit_publisher = ShareAuditPublisher()


def get_share_audit_publisher() -> ShareAuditPublisher:
    """FastAPI dependency returning the process-wide publisher."""
    return share_audit_publisher
