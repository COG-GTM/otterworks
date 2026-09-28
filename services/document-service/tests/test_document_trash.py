"""Tests for the document trash lifecycle: list, restore, permanent delete."""

import os
import uuid

import jwt
import pytest
from httpx import AsyncClient

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105
os.environ.setdefault("JWT_SECRET", TEST_JWT_SECRET)


def _other_user_headers() -> dict[str, str]:
    token = jwt.encode(
        {"user_id": str(uuid.uuid4())}, TEST_JWT_SECRET, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


async def _create(client: AsyncClient, owner_id: uuid.UUID, title: str) -> dict:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": title, "content": "body text", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_and_delete(
    client: AsyncClient, owner_id: uuid.UUID, title: str
) -> dict:
    document = await _create(client, owner_id, title)
    resp = await client.delete(f"/api/v1/documents/{document['id']}")
    assert resp.status_code == 204, resp.text
    return document


@pytest.mark.asyncio
async def test_trash_lists_only_deleted_documents(
    client: AsyncClient, owner_id: uuid.UUID
):
    live = await _create(client, owner_id, "Live")
    deleted = await _create_and_delete(client, owner_id, "Deleted")

    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = [item["id"] for item in data["items"]]
    assert ids == [deleted["id"]]
    assert live["id"] not in ids
    assert data["total"] == 1
    assert data["items"][0]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_trash_is_newest_first_and_paginated(
    client: AsyncClient, owner_id: uuid.UUID
):
    first = await _create_and_delete(client, owner_id, "First")
    second = await _create_and_delete(client, owner_id, "Second")

    resp = await client.get("/api/v1/documents/trash", params={"page": 1, "size": 1})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 2
    assert data["pages"] == 2
    assert [item["id"] for item in data["items"]] == [second["id"]]

    resp = await client.get("/api/v1/documents/trash", params={"page": 2, "size": 1})
    assert [item["id"] for item in resp.json()["items"]] == [first["id"]]


@pytest.mark.asyncio
async def test_trash_does_not_leak_other_owners_documents(
    client: AsyncClient, owner_id: uuid.UUID
):
    await _create_and_delete(client, owner_id, "Mine")

    resp = await client.get("/api/v1/documents/trash", headers=_other_user_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_trash_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/documents/trash", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_restore_brings_document_back_with_content_and_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    document = await _create(client, owner_id, "Restore Me")
    doc_id = document["id"]
    await client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Restore Me", "content": "second revision"},
    )
    assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204

    resp = await client.post(f"/api/v1/documents/{doc_id}/restore")
    assert resp.status_code == 200, resp.text
    restored = resp.json()
    assert restored["is_deleted"] is False
    assert restored["deleted_at"] is None
    assert restored["content"] == "second revision"

    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 200
    versions = (await client.get(f"/api/v1/documents/{doc_id}/versions")).json()
    assert [version["version_number"] for version in versions] == [2, 1]

    listed = (
        await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    ).json()
    assert any(item["id"] == doc_id for item in listed["items"])
    assert (await client.get("/api/v1/documents/trash")).json()["items"] == []


@pytest.mark.asyncio
async def test_restore_unknown_or_live_document_returns_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    resp = await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")
    assert resp.status_code == 404

    live = await _create(client, owner_id, "Still Here")
    resp = await client.post(f"/api/v1/documents/{live['id']}/restore")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_denied_for_other_owner(
    client: AsyncClient, owner_id: uuid.UUID
):
    document = await _create_and_delete(client, owner_id, "Not Yours")

    resp = await client.post(
        f"/api/v1/documents/{document['id']}/restore", headers=_other_user_headers()
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_permanent_delete_purges_document_and_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    document = await _create_and_delete(client, owner_id, "Purge Me")
    doc_id = document["id"]

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}", params={"permanent": "true"}
    )
    assert resp.status_code == 204, resp.text

    assert (await client.get("/api/v1/documents/trash")).json()["items"] == []
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404
    assert (await client.post(f"/api/v1/documents/{doc_id}/restore")).status_code == 404
    assert (
        await client.get(f"/api/v1/documents/{doc_id}/versions")
    ).status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_requires_a_trashed_document(
    client: AsyncClient, owner_id: uuid.UUID
):
    live = await _create(client, owner_id, "Live")

    resp = await client.delete(
        f"/api/v1/documents/{live['id']}", params={"permanent": "true"}
    )
    assert resp.status_code == 404
    assert (await client.get(f"/api/v1/documents/{live['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_permanent_delete_denied_for_other_owner(
    client: AsyncClient, owner_id: uuid.UUID
):
    document = await _create_and_delete(client, owner_id, "Not Yours")

    resp = await client.delete(
        f"/api/v1/documents/{document['id']}",
        params={"permanent": "true"},
        headers=_other_user_headers(),
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_default_delete_stays_a_soft_delete(
    client: AsyncClient, owner_id: uuid.UUID
):
    document = await _create_and_delete(client, owner_id, "Soft")

    assert (await client.get(f"/api/v1/documents/{document['id']}")).status_code == 404
    trash = (await client.get("/api/v1/documents/trash")).json()
    assert [item["id"] for item in trash["items"]] == [document["id"]]
