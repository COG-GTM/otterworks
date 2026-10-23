"""Only auth-service access tokens identify a caller; refresh tokens and headers do not."""

import time
import uuid

import jwt
import pytest
from httpx import AsyncClient

from tests.conftest import TEST_JWT_SECRET


def _token(user_id: uuid.UUID, **claims: object) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "iat": now, "exp": now + 3600, **claims}
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS384")


async def _create_owned_document(client: AsyncClient) -> str:
    created = await client.post("/api/v1/documents/", json={"title": "Owned", "content": "x"})
    assert created.status_code == 201
    return created.json()["id"]


@pytest.mark.asyncio
async def test_access_token_reads_own_document(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_owned_document(client)
    token = _token(owner_id, type="access")

    resp = await client.get(
        f"/api/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200
    assert resp.json()["owner_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_refresh_token_is_not_an_access_token(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_owned_document(client)
    now = int(time.time())
    refresh = _token(owner_id, type="refresh", jti=str(uuid.uuid4()), exp=now + 2592000)
    headers = {"Authorization": f"Bearer {refresh}"}

    assert (await client.get(f"/api/v1/documents/{doc_id}", headers=headers)).status_code == 401
    assert (await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)).status_code == 401
    assert (
        await client.post("/api/v1/documents/", json={"title": "x"}, headers=headers)
    ).status_code == 401


@pytest.mark.asyncio
async def test_token_without_type_is_rejected(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_owned_document(client)
    untyped = _token(owner_id)

    resp = await client.get(
        f"/api/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {untyped}"}
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unset_secret_does_not_trust_forwarded_user_id(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch
):
    doc_id = await _create_owned_document(client)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    resp = await client.get(
        f"/api/v1/documents/{doc_id}",
        headers={"Authorization": "Bearer anything", "X-User-ID": str(owner_id)},
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unset_secret_rejects_valid_access_token(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch
):
    doc_id = await _create_owned_document(client)
    token = _token(owner_id, type="access")
    monkeypatch.delenv("JWT_SECRET", raising=False)

    resp = await client.get(
        f"/api/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 401
