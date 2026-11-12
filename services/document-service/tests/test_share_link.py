"""Tests for read-only share-link tokens."""

import hashlib
import hmac
import uuid

import pytest

from app.services.share_link import ShareLinkService

DOC_ID = "11111111-1111-4111-8111-111111111111"
TEST_SECRET = "unit-test-share-link-secret-0123456789"  # noqa: S105


def _legacy_md5_token(document_id: str, salt: str = "otterworks-share") -> str:
    return hashlib.md5(f"{document_id}:{salt}".encode(), usedforsecurity=False).hexdigest()[:16]


@pytest.fixture
def service():
    return ShareLinkService(secret=TEST_SECRET)


def test_minted_token_verifies(service):
    assert service.verify_token(DOC_ID, service.mint_token(DOC_ID)) is True


def test_token_is_stable_across_calls(service):
    assert service.mint_token(DOC_ID) == service.mint_token(DOC_ID)


def test_token_of_another_document_is_rejected(service):
    other = "22222222-2222-4222-8222-222222222222"
    assert service.verify_token(DOC_ID, service.mint_token(other)) is False


def test_garbage_token_is_rejected(service):
    assert service.verify_token(DOC_ID, "not-a-token") is False


def test_offline_md5_forgery_is_rejected(service):
    assert service.verify_token(DOC_ID, _legacy_md5_token(DOC_ID)) is False


def test_token_depends_on_secret(service):
    other = ShareLinkService(secret="a-different-share-link-secret-987654")
    assert other.mint_token(DOC_ID) != service.mint_token(DOC_ID)
    assert other.verify_token(DOC_ID, service.mint_token(DOC_ID)) is False


def test_token_is_hmac_sha256_over_document_id(service):
    expected = "a0f6f0b45dc089e4bd194ced6dc188c95385018e8bbfcddc60fe4a5388681222"
    assert service.mint_token(DOC_ID) == expected
    assert (
        hmac.new(
            TEST_SECRET.encode(), b"otterworks.share-link.v1:" + DOC_ID.encode(), hashlib.sha256
        ).hexdigest()
        == expected
    )


def test_token_reads_secret_from_environment(monkeypatch):
    monkeypatch.setenv("SHARE_LINK_SECRET", TEST_SECRET)
    assert ShareLinkService().mint_token(DOC_ID) == ShareLinkService(secret=TEST_SECRET).mint_token(
        DOC_ID
    )


@pytest.mark.parametrize("secret", ["", "short-secret", "otterworks-share"])
def test_unusable_secret_fails_closed(secret):
    weak = ShareLinkService(secret=secret)
    with pytest.raises(RuntimeError):
        weak.mint_token(DOC_ID)
    assert weak.verify_token(DOC_ID, _legacy_md5_token(DOC_ID)) is False
    assert (
        weak.verify_token(DOC_ID, ShareLinkService(secret=TEST_SECRET).mint_token(DOC_ID)) is False
    )
    keyed_with_weak = hmac.new(
        secret.encode(), b"otterworks.share-link.v1:" + DOC_ID.encode(), hashlib.sha256
    ).hexdigest()
    assert weak.verify_token(DOC_ID, keyed_with_weak) is False


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


@pytest.mark.asyncio
async def test_shared_endpoint_rejects_legacy_md5_token(client, owner_id: uuid.UUID, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    created = await client.post(
        "/api/v1/documents/",
        json={"title": "Private", "content": "secret body", "owner_id": str(owner_id)},
    )
    doc_id = created.json()["id"]

    forged = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": _legacy_md5_token(doc_id)},
    )
    assert forged.status_code == 403


@pytest.mark.asyncio
async def test_share_endpoints_fail_closed_without_secret(client, owner_id: uuid.UUID, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    created = await client.post(
        "/api/v1/documents/",
        json={"title": "Private", "content": "secret body", "owner_id": str(owner_id)},
    )
    doc_id = created.json()["id"]
    headers = {"Authorization": "Bearer token", "X-User-ID": str(owner_id)}
    issued = await client.post(f"/api/v1/documents/{doc_id}/share", headers=headers)
    assert issued.status_code == 200
    previously_valid = issued.json()["token"]

    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    minted = await client.post(f"/api/v1/documents/{doc_id}/share", headers=headers)
    assert minted.status_code == 503

    stale = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": previously_valid},
    )
    assert stale.status_code == 403

    forged = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": _legacy_md5_token(doc_id)},
    )
    assert forged.status_code == 403
