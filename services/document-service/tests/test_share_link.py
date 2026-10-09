"""Tests for read-only share-link tokens."""

import hashlib
import uuid

import pytest

from app.services.share_link import ShareLinkNotConfiguredError, ShareLinkService

DOC_ID = "11111111-1111-4111-8111-111111111111"


def _legacy_md5_token(document_id: str) -> str:
    """The pre-HMAC token anyone could derive from the id and the source-visible salt."""
    digest = hashlib.md5(f"{document_id}:otterworks-share".encode(), usedforsecurity=False)
    return digest.hexdigest()[:16]


@pytest.fixture
def service():
    return ShareLinkService(secret="unit-test-share-secret-0123456789")


def test_minted_token_verifies(service):
    assert service.verify_token(DOC_ID, service.mint_token(DOC_ID)) is True


def test_token_is_stable_across_calls(service):
    assert service.mint_token(DOC_ID) == service.mint_token(DOC_ID)


def test_token_of_another_document_is_rejected(service):
    other = "22222222-2222-4222-8222-222222222222"
    assert service.verify_token(DOC_ID, service.mint_token(other)) is False


def test_garbage_token_is_rejected(service):
    assert service.verify_token(DOC_ID, "not-a-token") is False


def test_offline_md5_derivation_is_rejected(service):
    assert service.verify_token(DOC_ID, _legacy_md5_token(DOC_ID)) is False


def test_token_depends_on_the_secret(service):
    other = ShareLinkService(secret="a-different-share-secret-9876543210")
    token = service.mint_token(DOC_ID)
    assert other.mint_token(DOC_ID) != token
    assert other.verify_token(DOC_ID, token) is False


def test_non_ascii_token_is_rejected_without_error(service):
    assert service.verify_token(DOC_ID, "\u00e9" * 32) is False


@pytest.mark.parametrize("secret", ["", "too-short"])
def test_missing_or_weak_secret_fails_closed(secret):
    service = ShareLinkService(secret=secret)
    with pytest.raises(ShareLinkNotConfiguredError):
        service.mint_token(DOC_ID)
    assert service.verify_token(DOC_ID, "0" * 32) is False


def test_secret_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("SHARE_LINK_SECRET", "env-share-secret-abcdefghijkl")
    expected = ShareLinkService(secret="env-share-secret-abcdefghijkl").mint_token(DOC_ID)
    assert ShareLinkService().mint_token(DOC_ID) == expected
    monkeypatch.delenv("SHARE_LINK_SECRET")
    with pytest.raises(ShareLinkNotConfiguredError):
        ShareLinkService().mint_token(DOC_ID)


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
async def test_share_endpoints_fail_closed_without_secret(
    client, owner_id: uuid.UUID, monkeypatch
):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    created = await client.post(
        "/api/v1/documents/",
        json={"title": "Shared", "content": "body", "owner_id": str(owner_id)},
    )
    doc_id = created.json()["id"]
    headers = {"Authorization": "Bearer token", "X-User-ID": str(owner_id)}
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)

    minted = await client.post(f"/api/v1/documents/{doc_id}/share", headers=headers)
    assert minted.status_code == 503

    shared = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": _legacy_md5_token(doc_id)},
    )
    assert shared.status_code == 403
