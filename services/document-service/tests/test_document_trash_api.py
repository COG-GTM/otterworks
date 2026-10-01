"""Tests for the document trash lifecycle: list, restore, permanent delete."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import bearer_auth


async def _create(client: AsyncClient, owner_id: uuid.UUID, title: str = "Doc") -> dict:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": title, "content": "body text", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_trash_is_empty_initially(client: AsyncClient):
    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_trash_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/documents/trash", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_deleted_document_appears_in_trash(client: AsyncClient, owner_id: uuid.UUID):
    kept = await _create(client, owner_id, "Kept")
    doomed = await _create(client, owner_id, "Doomed")

    resp = await client.delete(f"/api/v1/documents/{doomed['id']}")
    assert resp.status_code == 204

    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == [doomed["id"]]
    assert data["items"][0]["is_deleted"] is True
    assert data["items"][0]["deleted_at"] is not None

    listing = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert [item["id"] for item in listing.json()["items"]] == [kept["id"]]


@pytest.mark.asyncio
async def test_trash_is_paginated_newest_deletion_first(client: AsyncClient, owner_id: uuid.UUID):
    ids = []
    for i in range(3):
        doc = await _create(client, owner_id, f"Doc {i}")
        ids.append(doc["id"])
    for doc_id in ids:
        await client.delete(f"/api/v1/documents/{doc_id}")

    resp = await client.get("/api/v1/documents/trash", params={"page": 1, "size": 2})
    data = resp.json()
    assert data["total"] == 3
    assert data["pages"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["id"] == ids[-1]

    resp = await client.get("/api/v1/documents/trash", params={"page": 2, "size": 2})
    assert [item["id"] for item in resp.json()["items"]] == [ids[0]]


@pytest.mark.asyncio
async def test_trash_only_lists_callers_documents(client: AsyncClient, owner_id: uuid.UUID):
    other = uuid.uuid4()
    mine = await _create(client, owner_id, "Mine")
    theirs = await _create(client, other, "Theirs")
    await client.delete(f"/api/v1/documents/{mine['id']}")
    await client.delete(f"/api/v1/documents/{theirs['id']}", auth=bearer_auth(other))

    resp = await client.get("/api/v1/documents/trash")
    assert [item["id"] for item in resp.json()["items"]] == [mine["id"]]

    resp = await client.get("/api/v1/documents/trash", auth=bearer_auth(other))
    assert [item["id"] for item in resp.json()["items"]] == [theirs["id"]]


@pytest.mark.asyncio
async def test_restore_brings_document_back_with_content_and_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id, "Restore Me")
    await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Restore Me", "content": "second draft"},
    )
    await client.delete(f"/api/v1/documents/{doc['id']}")
    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 404

    resp = await client.post(f"/api/v1/documents/{doc['id']}/restore")
    assert resp.status_code == 200
    restored = resp.json()
    assert restored["id"] == doc["id"]
    assert restored["is_deleted"] is False
    assert restored["deleted_at"] is None
    assert restored["content"] == "second draft"
    assert restored["version"] == 2

    resp = await client.get(f"/api/v1/documents/{doc['id']}")
    assert resp.status_code == 200
    versions = await client.get(f"/api/v1/documents/{doc['id']}/versions")
    assert [v["version_number"] for v in versions.json()] == [2, 1]

    trash = await client.get("/api/v1/documents/trash")
    assert trash.json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_unknown_or_live_document_is_404(client: AsyncClient, owner_id: uuid.UUID):
    resp = await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")
    assert resp.status_code == 404

    live = await _create(client, owner_id, "Live")
    resp = await client.post(f"/api/v1/documents/{live['id']}/restore")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_denied_for_other_owner(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id, "Private")
    await client.delete(f"/api/v1/documents/{doc['id']}")

    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/restore", auth=bearer_auth(uuid.uuid4())
    )
    assert resp.status_code == 403

    trash = await client.get("/api/v1/documents/trash")
    assert trash.json()["total"] == 1


@pytest.mark.asyncio
async def test_permanent_delete_removes_document_versions_and_comments(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id, "Purge Me")
    await client.post(
        f"/api/v1/documents/{doc['id']}/comments",
        json={"author_id": str(owner_id), "content": "a note"},
    )
    await client.delete(f"/api/v1/documents/{doc['id']}")

    resp = await client.delete(f"/api/v1/documents/{doc['id']}", params={"permanent": "true"})
    assert resp.status_code == 204

    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0
    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 404
    assert (await client.post(f"/api/v1/documents/{doc['id']}/restore")).status_code == 404
    assert (await client.get(f"/api/v1/documents/{doc['id']}/versions")).status_code == 404
    assert (await client.get(f"/api/v1/documents/{doc['id']}/comments")).json() == []
    resp = await client.delete(f"/api/v1/documents/{doc['id']}", params={"permanent": "true"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_denied_for_other_owner(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id, "Private")
    await client.delete(f"/api/v1/documents/{doc['id']}")

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}",
        params={"permanent": "true"},
        auth=bearer_auth(uuid.uuid4()),
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_default_delete_still_soft_deletes(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id, "Soft")
    resp = await client.delete(f"/api/v1/documents/{doc['id']}")
    assert resp.status_code == 204
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1
