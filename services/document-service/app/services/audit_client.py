"""Sends audit events to audit-service."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()


class AuditDeliveryError(RuntimeError):
    """Raised when a required audit event could not be recorded."""


class AuditClient:
    """Posts events to audit-service's ``POST /api/v1/audit/events``.

    When ``audit_service_url`` is configured, delivery is required: a failure raises
    ``AuditDeliveryError`` so the caller can roll back the change being audited.
    Without a URL the event is only logged.
    """

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url if base_url is not None else settings.audit_service_url).rstrip(
            "/"
        )
        self.timeout = timeout if timeout is not None else settings.audit_timeout_seconds

    async def record(
        self,
        *,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        workspace_id: str,
        old_value: str | None,
        new_value: str | None,
    ) -> None:
        timestamp = datetime.now(UTC).isoformat()
        details = {
            "workspace_id": workspace_id,
            "old_value": old_value or "",
            "new_value": new_value or "",
            "timestamp": timestamp,
        }
        logger.info(
            "audit_event",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            **details,
        )
        if not self.base_url:
            return
        body = {
            "userId": actor_id,
            "action": action,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "details": details,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/v1/audit/events", json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("audit_event_delivery_failed", action=action, error=str(exc))
            raise AuditDeliveryError(action) from exc


audit_client = AuditClient()
