"""Identity is only ever taken from a verified JWT, never from X-User-ID."""

import uuid

import pytest
from httpx import AsyncClient

from app.api.documents import require_jwt_secret
from app.main import app, lifespan


async def _create_doc(client: AsyncClient, owner_id: uuid.UUID) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Private", "content": "secret", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_x_user_id_with_invalid_token_is_rejected(client: AsyncClient, owner_id):
    doc_id = await _create_doc(client, owner_id)
    headers = {"Authorization": "Bearer x", "X-User-ID": str(owner_id)}

    resp = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_x_user_id_is_ignored_without_jwt_secret(
    client: AsyncClient, owner_id, monkeypatch
):
    doc_id = await _create_doc(client, owner_id)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    headers = {"Authorization": "Bearer x", "X-User-ID": str(owner_id)}

    for method, path in [
        ("GET", f"/api/v1/documents/{doc_id}"),
        ("POST", f"/api/v1/documents/{doc_id}/share"),
        ("DELETE", f"/api/v1/documents/{doc_id}"),
    ]:
        resp = await client.request(method, path, headers=headers)
        assert resp.status_code == 401, (method, path, resp.status_code)


def test_require_jwt_secret_raises_when_unset(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        require_jwt_secret()


@pytest.mark.asyncio
async def test_startup_fails_without_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        async with lifespan(app):
            pass
