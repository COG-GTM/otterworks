"""Fire-and-forget client for the audit-service ingest API.

Events follow the v2 audit wire contract (``POST {AUDIT_SERVICE_URL}/api/v1/audit/events``).
Emitting never affects the caller's response: each event is sent on its own task with a
short timeout and one retry, and a final failure is logged and counted in
``audit_emit_failures_total`` instead of being raised.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

SERVICE_NAME = "document-service"
EVENTS_PATH = "/api/v1/audit/events"
DEFAULT_TIMEOUT_SECONDS = 2.0
MAX_ATTEMPTS = 2

_failures_total = 0


def emit_failures_total() -> int:
    return _failures_total


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AuditClient:
    """Sends audit events to audit-service without blocking the request path."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._pending: set[asyncio.Task[None]] = set()

    @staticmethod
    def _base_url() -> str:
        return os.environ.get("AUDIT_SERVICE_URL", "").rstrip("/")

    @staticmethod
    def _timeout() -> float:
        try:
            return float(os.environ.get("AUDIT_SERVICE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
        except ValueError:
            return DEFAULT_TIMEOUT_SECONDS

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout()), transport=self._transport
            )
        return self._http

    def submit(self, event: dict[str, Any]) -> None:
        """Schedule ``event`` for delivery and return immediately."""
        if not self._base_url():
            logger.debug("audit_emit_skipped", reason="AUDIT_SERVICE_URL unset")
            return
        task = asyncio.get_running_loop().create_task(self.send(event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def send(self, event: dict[str, Any]) -> bool:
        """Deliver one event, retrying once on 5xx or transport errors. Never raises."""
        global _failures_total
        url = f"{self._base_url()}{EVENTS_PATH}"
        headers = {
            "Content-Type": "application/json",
            "X-Audit-Token": os.environ.get("AUDIT_SERVICE_TOKEN", ""),
        }
        if event.get("requestId"):
            headers["X-Request-ID"] = event["requestId"]

        error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = await self._client().post(url, json=event, headers=headers)
            except httpx.HTTPError as exc:
                error = type(exc).__name__
            except Exception as exc:  # noqa: BLE001 - auditing must never break a request
                error = type(exc).__name__
                break
            else:
                if resp.status_code < 400:
                    return True
                error = f"HTTP {resp.status_code}"
                if resp.status_code < 500:
                    break
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(0.1 * attempt)

        _failures_total += 1
        logger.warning(
            "audit_emit_failed",
            action=event.get("action"),
            request_id=event.get("requestId"),
            error=error,
            audit_emit_failures_total=_failures_total,
        )
        return False

    async def drain(self) -> None:
        """Wait for in-flight events (used on shutdown and in tests)."""
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def aclose(self) -> None:
        await self.drain()
        if self._http is not None:
            await self._http.aclose()
            self._http = None


_audit_client = AuditClient()


def get_audit_client() -> AuditClient:
    return _audit_client


def set_audit_client(client: AuditClient) -> AuditClient:
    """Swap the process-wide client, returning the previous one."""
    global _audit_client
    previous, _audit_client = _audit_client, client
    return previous
