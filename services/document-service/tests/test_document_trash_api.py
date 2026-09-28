"""Tests for the document trash, restore and permanent-delete endpoints."""

import os
import uuid

import jwt
import pytest
from httpx import AsyncClient

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105
os.environ.setdefault("JWT_SECRET", TEST_JWT_SECRET)


def _auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    token = jwt.encode({"user_id": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _create_document(
    client: AsyncClient, owner_id: uuid.UUID, title: str = "Doc", content: str = "Body"
) -> dict:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": title, "content": content, "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_trash_lists_deleted_documents(client: AsyncClient, owner_id: uuid.UUID):
    deleted = await _create_document(client, owner_id, title="Deleted")
    kept = await _create_document(client, owner_id, title="Kept")

    assert (await client.delete(f"/api/v1/documents/{deleted['id']}")).status_code == 204

    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [deleted["id"]]
    assert body["items"][0]["is_deleted"] is True
    assert body["items"][0]["deleted_at"] is not None

    listing = await client.get("/api/v1/documents/")
    assert [item["id"] for item in listing.json()["items"]] == [kept["id"]]


@pytest.mark.asyncio
async def test_trash_is_paginated_newest_first(
    client: AsyncClient, owner_id: uuid.UUID
):
    ids = []
    for i in range(3):
        doc = await _create_document(client, owner_id, title=f"Doc {i}")
        await client.delete(f"/api/v1/documents/{doc['id']}")
        ids.append(doc["id"])

    resp = await client.get("/api/v1/documents/trash", params={"page": 1, "size": 2})
    body = resp.json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] == ids[-1]


@pytest.mark.asyncio
async def test_trash_does_not_leak_other_owners(
    client: AsyncClient, owner_id: uuid.UUID
):
    other_owner = uuid.uuid4()
    other_doc = await _create_document(client, other_owner, title="Theirs")
    await client.delete(
        f"/api/v1/documents/{other_doc['id']}", headers=_auth_headers(other_owner)
    )

    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_brings_document_back_with_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id, content="first body")
    await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Doc v2", "content": "second body"},
    )
    await client.delete(f"/api/v1/documents/{doc['id']}")

    resp = await client.post(f"/api/v1/documents/{doc['id']}/restore")
    assert resp.status_code == 200
    restored = resp.json()
    assert restored["is_deleted"] is False
    assert restored["deleted_at"] is None
    assert restored["content"] == "second body"

    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 200
    versions = await client.get(f"/api/v1/documents/{doc['id']}/versions")
    assert [v["version_number"] for v in versions.json()] == [2, 1]
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_unknown_or_live_document_is_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    live = await _create_document(client, owner_id)
    assert (
        await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/documents/{live['id']}/restore")
    ).status_code == 404


@pytest.mark.asyncio
async def test_restore_denied_for_other_owner(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create_document(client, owner_id)
    await client.delete(f"/api/v1/documents/{doc['id']}")

    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/restore", headers=_auth_headers(uuid.uuid4())
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_permanent_delete_purges_trashed_document(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)
    await client.post(
        f"/api/v1/documents/{doc['id']}/comments",
        json={"author_id": str(owner_id), "content": "a note"},
    )
    await client.delete(f"/api/v1/documents/{doc['id']}")

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}", params={"permanent": "true"}
    )
    assert resp.status_code == 204
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0
    assert (
        await client.post(f"/api/v1/documents/{doc['id']}/restore")
    ).status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_requires_a_trashed_document(
    client: AsyncClient, owner_id: uuid.UUID
):
    live = await _create_document(client, owner_id)
    resp = await client.delete(
        f"/api/v1/documents/{live['id']}", params={"permanent": "true"}
    )
    assert resp.status_code == 404
    assert (await client.get(f"/api/v1/documents/{live['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_permanent_delete_denied_for_other_owner(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)
    await client.delete(f"/api/v1/documents/{doc['id']}")

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}",
        params={"permanent": "true"},
        headers=_auth_headers(uuid.uuid4()),
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_trash_requires_authentication(client: AsyncClient):
    assert (await client.get("/api/v1/documents/trash", auth=None)).status_code == 401
