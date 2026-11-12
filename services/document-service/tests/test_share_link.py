"""Tests for read-only share-link tokens."""

import hashlib
import hmac
import uuid

import pytest

from app.services.share_link import ShareLinkService, ShareLinkUnavailableError

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


def test_unkeyed_md5_token_is_rejected(service):
    forged = hashlib.md5(  # noqa: S324 - reproducing the legacy forgeable token
        f"{DOC_ID}:otterworks-share".encode(), usedforsecurity=False
    ).hexdigest()[:16]
    assert service.verify_token(DOC_ID, forged) is False


def test_token_depends_on_secret():
    assert ShareLinkService(secret="a").mint_token(DOC_ID) != ShareLinkService(
        secret="b"
    ).mint_token(DOC_ID)


def test_token_is_hmac_sha256_of_document_id(service):
    expected = hmac.new(b"test-share-secret", DOC_ID.encode(), hashlib.sha256).hexdigest()
    assert service.mint_token(DOC_ID) == expected


def test_jwt_fallback_key_is_domain_separated_hmac(monkeypatch):
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    monkeypatch.setenv("JWT_SECRET", "jwt")
    key = hmac.new(b"jwt", b"otterworks-share-link-v1", hashlib.sha256).digest()
    expected = hmac.new(key, DOC_ID.encode(), hashlib.sha256).hexdigest()
    assert ShareLinkService().mint_token(DOC_ID) == expected


def test_non_ascii_token_is_rejected(service):
    assert service.verify_token(DOC_ID, "\u00e9" * 64) is False


def test_dedicated_secret_env_is_preferred(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt")
    monkeypatch.setenv("SHARE_LINK_SECRET", "dedicated")
    assert ShareLinkService().mint_token(DOC_ID) == ShareLinkService(secret="dedicated").mint_token(
        DOC_ID
    )


def test_falls_back_to_key_derived_from_jwt_secret(monkeypatch):
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    monkeypatch.setenv("JWT_SECRET", "jwt")
    token = ShareLinkService().mint_token(DOC_ID)
    assert ShareLinkService().verify_token(DOC_ID, token) is True
    assert token != ShareLinkService(secret="jwt").mint_token(DOC_ID)


def test_without_any_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    service = ShareLinkService()
    with pytest.raises(ShareLinkUnavailableError):
        service.mint_token(DOC_ID)
    assert service.verify_token(DOC_ID, "anything") is False


@pytest.mark.asyncio
async def test_share_endpoint_round_trip(client, owner_id: uuid.UUID, monkeypatch):
    # tests/test_documents_api.py sets JWT_SECRET at import time, which switches the
    # app off the X-User-ID fallback for the whole session. Drop it here so the
    # identity path this test exercises is the same whichever tests ran first.
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("SHARE_LINK_SECRET", "test-share-secret")
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


@pytest.mark.asyncio
async def test_share_endpoint_without_secret_returns_503(client, owner_id: uuid.UUID, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    created = await client.post(
        "/api/v1/documents/",
        json={"title": "Unshareable", "content": "body", "owner_id": str(owner_id)},
    )
    doc_id = created.json()["id"]
    headers = {"Authorization": "Bearer token", "X-User-ID": str(owner_id)}

    minted = await client.post(f"/api/v1/documents/{doc_id}/share", headers=headers)
    assert minted.status_code == 503

    shared = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": "anything"}
    )
    assert shared.status_code == 403
