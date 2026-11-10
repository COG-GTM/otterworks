"""Best-effort audit event delivery to services/audit-service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()


class AuditSink(Protocol):
    async def send(self, event: dict[str, Any]) -> bool | None: ...


class HttpAuditSink:
    """POSTs events to audit-service ``/api/v1/audit/events``."""

    async def send(self, event: dict[str, Any]) -> bool:
        if not settings.audit_service_url:
            logger.warning("audit_event_skipped", action=event.get("action"))
            return False
        url = f"{settings.audit_service_url.rstrip('/')}/api/v1/audit/events"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.post(url, json=event)
                resp.raise_for_status()
        except Exception:
            logger.exception("audit_event_delivery_failed", action=event.get("action"))
            return False
        return True


class AuditClient:
    def __init__(self, sink: AuditSink | None = None) -> None:
        self.sink: AuditSink = sink or HttpAuditSink()

    async def record(
        self,
        *,
        event: str,
        actor_id: str,
        workspace_id: str,
        resource_type: str,
        resource_id: str,
        old_value: str | None,
        new_value: str | None,
        extra: dict[str, str] | None = None,
    ) -> bool:
        """Send the event; return True when the sink confirmed delivery."""
        timestamp = datetime.now(UTC).isoformat()
        details = {
            "event": event,
            "workspace_id": workspace_id,
            "old_value": old_value or "",
            "new_value": new_value or "",
            "timestamp": timestamp,
            **(extra or {}),
        }
        payload = {
            "userId": actor_id,
            "action": event,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "details": details,
        }
        logger.info("audit_event_recorded", audit=details, actor_id=actor_id)
        return (await self.sink.send(payload)) is not False


audit_client = AuditClient()
