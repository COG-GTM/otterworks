"""Caller identity comes only from a verified JWT, never from X-User-ID."""

import uuid

import jwt
import pytest
from httpx import AsyncClient

from app.main import app, lifespan
from tests.conftest import TEST_JWT_SECRET


async def _create_owned_document(client: AsyncClient) -> str:
    created = await client.post("/api/v1/documents/", json={"title": "Victim doc"})
    assert created.status_code == 201
    return created.json()["id"]


@pytest.mark.asyncio
async def test_x_user_id_not_trusted_when_jwt_secret_unset(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch
):
    doc_id = await _create_owned_document(client)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    headers = {"Authorization": "Bearer x", "X-User-ID": str(owner_id)}

    for method in ("GET", "DELETE"):
        resp = await client.request(method, f"/api/v1/documents/{doc_id}", headers=headers)
        assert resp.status_code == 401, method
    resp = await client.put(
        f"/api/v1/documents/{doc_id}", json={"title": "pwned"}, headers=headers
    )
    assert resp.status_code == 401
    resp = await client.post(f"/api/v1/documents/{doc_id}/share", headers=headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_rejected_when_jwt_secret_unset(
    client: AsyncClient, monkeypatch
):
    doc_id = await _create_owned_document(client)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    resp = await client.get(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_x_user_id_not_trusted_with_unverifiable_token(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_owned_document(client)
    forged = jwt.encode({"user_id": str(owner_id)}, "not-the-secret", algorithm="HS256")
    for token in ("x", forged):
        resp = await client.get(
            f"/api/v1/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}", "X-User-ID": str(owner_id)},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_x_user_id_does_not_override_jwt_identity(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_owned_document(client)
    attacker = jwt.encode({"user_id": str(uuid.uuid4())}, TEST_JWT_SECRET, algorithm="HS256")
    resp = await client.get(
        f"/api/v1/documents/{doc_id}",
        headers={"Authorization": f"Bearer {attacker}", "X-User-ID": str(owner_id)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_service_refuses_to_start_without_jwt_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_service_refuses_to_start_with_empty_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        async with lifespan(app):
            pass
