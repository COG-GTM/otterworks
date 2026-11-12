"""Tests for read-only share-link tokens."""

import hashlib
import hmac
import uuid

import pytest

from app.services.share_link import ShareLinkNotConfiguredError, ShareLinkService

DOC_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def service():
    return ShareLinkService(secret="test-share-secret")


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
    monkeypatch.setenv("SHARE_LINK_SECRET", "endpoint-share-secret")
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


def test_unkeyed_md5_token_is_rejected(service):
    forged = hashlib.md5(f"{DOC_ID}:otterworks-share".encode(), usedforsecurity=False)
    assert service.verify_token(DOC_ID, forged.hexdigest()[:16]) is False


def test_token_depends_on_secret():
    a = ShareLinkService(secret="secret-a").mint_token(DOC_ID)
    b = ShareLinkService(secret="secret-b").mint_token(DOC_ID)
    assert a != b
    assert ShareLinkService(secret="secret-b").verify_token(DOC_ID, a) is False


def test_falls_back_to_key_derived_from_jwt_secret(monkeypatch):
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    monkeypatch.setenv("JWT_SECRET", "jwt-secret")
    service = ShareLinkService()
    token = service.mint_token(DOC_ID)
    assert service.verify_token(DOC_ID, token) is True
    assert token != ShareLinkService(secret="jwt-secret").mint_token(DOC_ID)

    derived = hmac.new(b"jwt-secret", b"otterworks/share-link/v1", hashlib.sha256).digest()
    assert token == hmac.new(derived, DOC_ID.encode(), hashlib.sha256).hexdigest()

    monkeypatch.setenv("JWT_SECRET", "rotated-jwt-secret")
    rotated = ShareLinkService()
    assert rotated.mint_token(DOC_ID) != token
    assert rotated.verify_token(DOC_ID, token) is False


def test_fails_closed_without_any_secret(monkeypatch):
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    service = ShareLinkService()
    assert service.verify_token(DOC_ID, "anything") is False
    with pytest.raises(ShareLinkNotConfiguredError):
        service.mint_token(DOC_ID)


@pytest.mark.asyncio
async def test_forged_md5_token_gets_403(client, owner_id: uuid.UUID, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("SHARE_LINK_SECRET", "endpoint-share-secret")
    created = await client.post(
        "/api/v1/documents/",
        json={"title": "Private", "content": "body", "owner_id": str(owner_id)},
    )
    doc_id = created.json()["id"]
    forged = hashlib.md5(f"{doc_id}:otterworks-share".encode(), usedforsecurity=False)
    response = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": forged.hexdigest()[:16]},
    )
    assert response.status_code == 403
