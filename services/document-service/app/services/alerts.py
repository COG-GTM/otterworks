"""Fire-and-forget trigger for the Devin Automation that investigates failed creates.

``POST {DEVIN_AUTOMATION_WEBHOOK_URL}`` with the ``X-Webhook-Secret`` header
starts one Devin session per failed "New document" click. Delivery is skipped
when the URL is unset.
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

_pending: set[asyncio.Task[None]] = set()


def build_document_create_failure_payload(
    title: str, error: str, reporter_email: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "alert": DOCUMENT_CREATE_FAILED,
        "service": "document-service",
        "repository": "COG-GTM/otterworks",
        "summary": f"Document creation failed: {title}",
        "title": title,
        "error": error,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    email = (reporter_email or "").strip()
    if email:
        payload["reporter_email"] = email
    return payload


async def _deliver(payload: dict[str, Any]) -> None:
    url = os.environ.get("DEVIN_AUTOMATION_WEBHOOK_URL", "").strip()
    if not url:
        logger.warning("devin_automation_webhook_skipped_no_url")
        return
    headers = {}
    secret = os.environ.get("DEVIN_AUTOMATION_WEBHOOK_SECRET", "").strip()
    if secret:
        headers["X-Webhook-Secret"] = secret
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        logger.info("devin_automation_webhook_delivered", status_code=resp.status_code)
    except httpx.HTTPError as exc:
        logger.error("devin_automation_webhook_failed", error=str(exc))


def notify_document_create_failure(title: str, error: str, reporter_email: str | None) -> None:
    """Schedule the webhook call without delaying or failing the caller's response."""
    payload = build_document_create_failure_payload(title, error, reporter_email)
    task = asyncio.create_task(_deliver(payload))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
