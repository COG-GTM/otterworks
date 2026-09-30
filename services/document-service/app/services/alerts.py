"""Fire-and-forget alert delivery to admin-service's Grafana-style ingest endpoint.

``POST {ADMIN_SERVICE_URL}/api/v1/admin/alerts/ingest`` turns each alert into an
incident and a Slack message. Payloads carry ``dedup=false`` so every failed
click opens its own incident instead of collapsing onto an open one.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

DOCUMENT_CREATE_FAILED = "DocumentCreateFailed"
DEFAULT_ADMIN_SERVICE_URL = "http://admin-service:8089"

_pending: set[asyncio.Task[None]] = set()


def build_document_create_failure_payload(
    title: str, error: str, reporter_email: str | None
) -> dict[str, Any]:
    labels = {
        "alertname": DOCUMENT_CREATE_FAILED,
        "severity": "critical",
        "affected_service": "document-service",
        "dedup": "false",
    }
    email = (reporter_email or "").strip()
    if email:
        labels["reporter_email"] = email
    return {
        "receiver": "otterworks-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": labels,
                "annotations": {
                    "summary": f"Document creation failed: {title}",
                    "description": (
                        f'Creating document "{title}" failed in document-service: {error}'
                    ),
                },
                "startsAt": datetime.now(UTC).isoformat(),
            }
        ],
    }


async def _deliver(payload: dict[str, Any]) -> None:
    base_url = os.environ.get("ADMIN_SERVICE_URL", DEFAULT_ADMIN_SERVICE_URL).rstrip("/")
    if not base_url:
        logger.warning("alert_skipped_no_admin_service_url")
        return
    headers = {}
    secret = os.environ.get("ALERT_WEBHOOK_SECRET", "").strip()
    if secret:
        headers["X-Alert-Secret"] = secret
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{base_url}/api/v1/admin/alerts/ingest", json=payload, headers=headers
            )
        logger.info("alert_delivered", status_code=resp.status_code)
    except httpx.HTTPError as exc:
        logger.error("alert_delivery_failed", error=str(exc))


def notify_document_create_failure(title: str, error: str, reporter_email: str | None) -> None:
    """Schedule the alert without delaying or failing the caller's response."""
    payload = build_document_create_failure_payload(title, error, reporter_email)
    task = asyncio.create_task(_deliver(payload))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
