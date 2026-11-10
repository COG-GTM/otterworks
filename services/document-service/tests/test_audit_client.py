"""Tests for the non-blocking audit-service client."""

import asyncio
import time
import uuid

import httpx
import pytest

from app.services import audit_client
from app.services.audit_client import AuditClient


def _event() -> dict:
    return {
        "userId": "anonymous",
        "action": "share.access",
        "resourceType": "share_link",
        "resourceId": str(uuid.uuid4()),
        "outcome": "denied",
        "serviceName": "document-service",
        "requestId": "req-1",
    }


@pytest.mark.asyncio
async def test_slow_audit_service_does_not_delay_the_response(client, owner_id, audit_sink):
    released = asyncio.Event()

    async def _slow(request: httpx.Request) -> httpx.Response:
        audit_sink.requests.append(request)
        await asyncio.wait_for(released.wait(), timeout=5)
        return httpx.Response(201)

    audit_sink.client = AuditClient(transport=httpx.MockTransport(_slow))
    previous = audit_client.set_audit_client(audit_sink.client)
    try:
        doc = await client.post(
            "/api/v1/documents/", json={"title": "T", "content": "c", "owner_id": str(owner_id)}
        )
        started = time.monotonic()
        resp = await client.delete(f"/api/v1/documents/{doc.json()['id']}")
        elapsed = time.monotonic() - started
        assert resp.status_code == 204
        assert elapsed < 1.0
        assert audit_sink.client._pending, "event should still be in flight"
    finally:
        released.set()
        await audit_sink.client.aclose()
        audit_client.set_audit_client(previous)


@pytest.mark.asyncio
async def test_client_error_is_not_retried(monkeypatch):
    monkeypatch.setenv("AUDIT_SERVICE_URL", "http://audit-service:8090")
    calls: list[httpx.Request] = []

    def _reject(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401)

    client = AuditClient(transport=httpx.MockTransport(_reject))
    before = audit_client.emit_failures_total()
    assert await client.send(_event()) is False
    assert len(calls) == 1
    assert audit_client.emit_failures_total() == before + 1
    await client.aclose()


@pytest.mark.asyncio
async def test_transient_failure_is_retried_once(monkeypatch):
    monkeypatch.setenv("AUDIT_SERVICE_URL", "http://audit-service:8090")
    replies = iter([httpx.Response(502), httpx.Response(201)])
    client = AuditClient(transport=httpx.MockTransport(lambda _req: next(replies)))
    before = audit_client.emit_failures_total()
    assert await client.send(_event()) is True
    assert audit_client.emit_failures_total() == before
    await client.aclose()


@pytest.mark.asyncio
async def test_nothing_is_sent_when_audit_service_url_is_unset():
    calls: list[httpx.Request] = []
    client = AuditClient(transport=httpx.MockTransport(lambda r: calls.append(r)))
    client.submit(_event())
    await client.drain()
    assert calls == []
