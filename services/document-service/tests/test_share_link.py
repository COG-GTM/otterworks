"""Tests for read-only share-link tokens."""

import uuid

import pytest

from app.services.share_link import ShareLinkService
from tests.conftest import CLIENT_IP, GATEWAY_HEADERS, REQUEST_ID

DOC_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def service():
    return ShareLinkService(salt="test-salt")


def test_minted_token_verifies(service):
    assert service.verify_token(DOC_ID, service.mint_token(DOC_ID)) is True


def test_token_is_stable_across_calls(service):
    assert service.mint_token(DOC_ID) == service.mint_token(DOC_ID)


def test_token_of_another_document_is_rejected(service):
    other = "22222222-2222-4222-8222-222222222222"
    assert service.verify_token(DOC_ID, service.mint_token(other)) is False


def test_garbage_token_is_rejected(service):
    assert service.verify_token(DOC_ID, "not-a-token") is False


@pytest.mark.asyncio
async def test_share_endpoint_round_trip(client, owner_id: uuid.UUID, monkeypatch):
    # tests/test_documents_api.py sets JWT_SECRET at import time, which switches the
    # app off the X-User-ID fallback for the whole session. Drop it here so the
    # identity path this test exercises is the same whichever tests ran first.
    monkeypatch.delenv("JWT_SECRET", raising=False)
    created = await client.post(
        "/api/v1/documents/",
        json={"title": "Shared", "content": "body", "owner_id": str(owner_id)},
    )
    doc_id = created.json()["id"]
    headers = {"Authorization": "Bearer token", "X-User-ID": str(owner_id)}

    minted = await client.post(f"/api/v1/documents/{doc_id}/share", headers=headers)
    assert minted.status_code == 200
    token = minted.json()["token"]

    shared = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": token}
    )
    assert shared.status_code == 200
    assert shared.json()["id"] == doc_id

    denied = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": "wrong"}
    )
    assert denied.status_code == 403


async def _create_doc(client, owner_id: uuid.UUID) -> str:
    created = await client.post(
        "/api/v1/documents/",
        json={"title": "Shared", "content": "secret body text", "owner_id": str(owner_id)},
    )
    return created.json()["id"]


@pytest.mark.asyncio
async def test_share_create_is_audited_without_the_token(client, owner_id, audit_sink):
    doc_id = await _create_doc(client, owner_id)
    minted = await client.post(f"/api/v1/documents/{doc_id}/share", headers=GATEWAY_HEADERS)
    assert minted.status_code == 200
    token = minted.json()["token"]

    event = await audit_sink.only("share.create")
    audit_sink.assert_request(
        event, user_id=str(owner_id), outcome="success", ip=CLIENT_IP, request_id=REQUEST_ID
    )
    assert event["resourceType"] == "share_link"
    assert event["resourceId"] == doc_id
    assert event["userAgent"] == "pytest-audit/1.0"
    assert token not in audit_sink.requests[0].content.decode()


@pytest.mark.asyncio
async def test_share_access_with_valid_token_is_audited(client, owner_id, audit_sink):
    doc_id = await _create_doc(client, owner_id)
    token = ShareLinkService().mint_token(doc_id)

    shared = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": token},
        headers=GATEWAY_HEADERS,
        auth=None,
    )
    assert shared.status_code == 200

    event = await audit_sink.only("share.access")
    audit_sink.assert_request(
        event, user_id="anonymous", outcome="success", ip=CLIENT_IP, request_id=REQUEST_ID
    )
    assert (event["resourceType"], event["resourceId"]) == ("share_link", doc_id)
    raw = b"".join(r.content for r in audit_sink.requests).decode()
    assert token not in raw
    assert "secret body text" not in raw


@pytest.mark.asyncio
async def test_share_access_with_invalid_token_is_audited_as_denied(client, owner_id, audit_sink):
    doc_id = await _create_doc(client, owner_id)
    denied = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": "forged-token-value"},
        headers=GATEWAY_HEADERS,
        auth=None,
    )
    assert denied.status_code == 403

    event = await audit_sink.only("share.access")
    audit_sink.assert_request(
        event, user_id="anonymous", outcome="denied", ip=CLIENT_IP, request_id=REQUEST_ID
    )
    assert event["resourceId"] == doc_id
    assert event["details"]["reason"] == "invalid_token"
    assert "forged-token-value" not in audit_sink.requests[0].content.decode()
