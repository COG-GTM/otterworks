"""Tests for read-only share-link tokens."""

import hashlib
import uuid

import pytest

from app.services.share_link import ShareLinkService, ShareLinkUnavailableError

DOC_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def service():
    return ShareLinkService(secret="test-secret")


def test_minted_token_verifies(service):
    assert service.verify_token(DOC_ID, service.mint_token(DOC_ID)) is True


def test_token_is_stable_across_calls(service):
    assert service.mint_token(DOC_ID) == service.mint_token(DOC_ID)


def test_token_of_another_document_is_rejected(service):
    other = "22222222-2222-4222-8222-222222222222"
    assert service.verify_token(DOC_ID, service.mint_token(other)) is False


def test_garbage_token_is_rejected(service):
    assert service.verify_token(DOC_ID, "not-a-token") is False


def test_legacy_md5_token_with_default_salt_is_rejected(service):
    forged = hashlib.md5(f"{DOC_ID}:otterworks-share".encode(), usedforsecurity=False).hexdigest()
    assert service.verify_token(DOC_ID, forged[:16]) is False
    assert service.verify_token(DOC_ID, forged) is False


def test_token_depends_on_secret():
    assert ShareLinkService(secret="a").mint_token(DOC_ID) != ShareLinkService(
        secret="b"
    ).mint_token(DOC_ID)


def test_missing_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ShareLinkUnavailableError):
        ShareLinkService()


def test_jwt_secret_fallback_is_domain_separated(monkeypatch):
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    monkeypatch.setenv("JWT_SECRET", "jwt-secret")
    derived = ShareLinkService()
    assert derived.verify_token(DOC_ID, derived.mint_token(DOC_ID)) is True
    assert derived.mint_token(DOC_ID) != ShareLinkService(secret="jwt-secret").mint_token(DOC_ID)


@pytest.mark.asyncio
async def test_shared_endpoint_rejects_forged_md5_token(client, owner_id: uuid.UUID, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("SHARE_LINK_SECRET", "endpoint-secret")
    created = await client.post(
        "/api/v1/documents/",
        json={"title": "Private", "content": "board memo", "owner_id": str(owner_id)},
    )
    doc_id = created.json()["id"]
    forged = hashlib.md5(f"{doc_id}:otterworks-share".encode(), usedforsecurity=False).hexdigest()
    resp = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": forged[:16]}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_shared_endpoint_unavailable_without_secret(client, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    resp = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": str(uuid.uuid4()), "token": "anything"},
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_share_endpoint_round_trip(client, owner_id: uuid.UUID, monkeypatch):
    # tests/test_documents_api.py sets JWT_SECRET at import time, which switches the
    # app off the X-User-ID fallback for the whole session. Drop it here so the
    # identity path this test exercises is the same whichever tests ran first.
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("SHARE_LINK_SECRET", "round-trip-secret")
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
