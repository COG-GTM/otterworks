"""Tests for comment API endpoints."""

import uuid

import jwt
import pytest
from httpx import AsyncClient

from tests.conftest import TEST_JWT_SECRET


def _auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    token = jwt.encode({"user_id": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _create_document(client: AsyncClient, owner_id: uuid.UUID) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Commented Doc", "content": "", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_add_comment(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"content": "Great document!"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Great document!"
    assert data["author_id"] == str(owner_id)
    assert data["document_id"] == doc_id


@pytest.mark.asyncio
async def test_add_comment_document_not_found(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/documents/{uuid.uuid4()}/comments",
        json={"content": "Orphan comment"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_comments(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    for i in range(3):
        await client.post(
            f"/api/v1/documents/{doc_id}/comments",
            json={"content": f"Comment {i}"},
        )

    resp = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_delete_comment(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    comment_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"content": "To delete"},
    )
    comment_id = comment_resp.json()["id"]

    resp = await client.delete(f"/api/v1/documents/{doc_id}/comments/{comment_id}")
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_delete_comment_not_found(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}/comments/{uuid.uuid4()}"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_comment_ignores_forged_author_id(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)
    victim = uuid.uuid4()

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(victim), "content": "Spoofed"},
    )
    assert resp.status_code == 201
    assert resp.json()["author_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_comment_routes_require_authentication(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)
    comment_id = (
        await client.post(
            f"/api/v1/documents/{doc_id}/comments", json={"content": "Mine"}
        )
    ).json()["id"]
    base = f"/api/v1/documents/{doc_id}/comments"

    post = await client.post(
        base,
        json={"author_id": str(owner_id), "content": "anon"},
        auth=None,
    )
    listed = await client.get(base, auth=None)
    deleted = await client.delete(
        f"{base}/{comment_id}", auth=None
    )

    assert post.status_code == 401
    assert listed.status_code == 401
    assert deleted.status_code == 401
    assert len((await client.get(base)).json()) == 1


@pytest.mark.asyncio
async def test_other_user_cannot_add_list_or_delete_comments(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)
    comment_id = (
        await client.post(
            f"/api/v1/documents/{doc_id}/comments", json={"content": "Private"}
        )
    ).json()["id"]
    base = f"/api/v1/documents/{doc_id}/comments"
    attacker = _auth_headers(uuid.uuid4())

    post = await client.post(
        base,
        json={"author_id": str(owner_id), "content": "as owner"},
        headers=attacker,
    )
    listed = await client.get(base, headers=attacker)
    deleted = await client.delete(f"{base}/{comment_id}", headers=attacker)

    assert post.status_code == 403
    assert listed.status_code == 403
    assert deleted.status_code == 403
    remaining = (await client.get(base)).json()
    assert [c["id"] for c in remaining] == [comment_id]
