"""Tests for the document trash lifecycle: list trash, restore, permanent delete."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import bearer_auth


async def _create(client: AsyncClient, owner_id: uuid.UUID, title: str) -> dict:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": title, "content": f"{title} body", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_trash_is_empty_before_any_delete(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Live")
    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_deleted_document_appears_in_trash_with_deleted_at(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id, "Trash Me")
    assert doc["deleted_at"] is None

    resp = await client.delete(f"/api/v1/documents/{doc['id']}")
    assert resp.status_code == 204

    listing = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert all(item["id"] != doc["id"] for item in listing.json()["items"])

    trash = await client.get("/api/v1/documents/trash")
    assert trash.status_code == 200
    data = trash.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["id"] == doc["id"]
    assert item["is_deleted"] is True
    assert item["deleted_at"] is not None


@pytest.mark.asyncio
async def test_trash_is_paginated_newest_first(client: AsyncClient, owner_id: uuid.UUID):
    ids = []
    for i in range(3):
        doc = await _create(client, owner_id, f"Doc {i}")
        ids.append(doc["id"])
    for doc_id in ids:
        assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204

    resp = await client.get("/api/v1/documents/trash", params={"page": 1, "size": 2})
    data = resp.json()
    assert data["total"] == 3
    assert data["pages"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["id"] == ids[-1]

    page2 = await client.get("/api/v1/documents/trash", params={"page": 2, "size": 2})
    assert [item["id"] for item in page2.json()["items"]] == [ids[0]]


@pytest.mark.asyncio
async def test_trash_requires_authentication(client: AsyncClient):
    resp = await client.get("/api/v1/documents/trash", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trash_only_lists_callers_documents(client: AsyncClient, owner_id: uuid.UUID):
    other_owner = uuid.uuid4()
    mine = await _create(client, owner_id, "Mine")
    theirs = await _create(client, other_owner, "Theirs")
    await client.delete(f"/api/v1/documents/{mine['id']}")
    await client.delete(
        f"/api/v1/documents/{theirs['id']}", auth=bearer_auth(other_owner)
    )

    resp = await client.get("/api/v1/documents/trash")
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids == [mine["id"]]

    other_resp = await client.get("/api/v1/documents/trash", auth=bearer_auth(other_owner))
    assert [item["id"] for item in other_resp.json()["items"]] == [theirs["id"]]


@pytest.mark.asyncio
async def test_restore_returns_document_to_list_with_content_and_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id, "Round Trip")
    await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Round Trip", "content": "second draft"},
    )
    assert (await client.delete(f"/api/v1/documents/{doc['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 404

    resp = await client.post(f"/api/v1/documents/{doc['id']}/restore")
    assert resp.status_code == 200, resp.text
    restored = resp.json()
    assert restored["id"] == doc["id"]
    assert restored["is_deleted"] is False
    assert restored["deleted_at"] is None
    assert restored["content"] == "second draft"
    assert restored["version"] == 2

    fetched = await client.get(f"/api/v1/documents/{doc['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "second draft"

    versions = await client.get(f"/api/v1/documents/{doc['id']}/versions")
    assert [v["version_number"] for v in versions.json()] == [2, 1]

    listing = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert any(item["id"] == doc["id"] for item in listing.json()["items"])

    trash = await client.get("/api/v1/documents/trash")
    assert trash.json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_unknown_or_live_document_is_404(client: AsyncClient, owner_id: uuid.UUID):
    resp = await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")
    assert resp.status_code == 404

    live = await _create(client, owner_id, "Still Live")
    resp = await client.post(f"/api/v1/documents/{live['id']}/restore")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_requires_authentication(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id, "Auth")
    await client.delete(f"/api/v1/documents/{doc['id']}")
    resp = await client.post(f"/api/v1/documents/{doc['id']}/restore", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cross_owner_restore_and_purge_denied(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id, "Private")
    await client.delete(f"/api/v1/documents/{doc['id']}")

    intruder = bearer_auth(uuid.uuid4())
    restore = await client.post(f"/api/v1/documents/{doc['id']}/restore", auth=intruder)
    assert restore.status_code == 403

    purge = await client.delete(
        f"/api/v1/documents/{doc['id']}", params={"permanent": "true"}, auth=intruder
    )
    assert purge.status_code == 403

    trash = await client.get("/api/v1/documents/trash")
    assert [item["id"] for item in trash.json()["items"]] == [doc["id"]]


@pytest.mark.asyncio
async def test_permanent_delete_removes_document_versions_and_comments(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id, "Purge Me")
    await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Purge Me", "content": "v2"},
    )
    comment = await client.post(
        f"/api/v1/documents/{doc['id']}/comments",
        json={"author_id": str(owner_id), "content": "note"},
    )
    assert comment.status_code == 201
    assert (await client.delete(f"/api/v1/documents/{doc['id']}")).status_code == 204

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}", params={"permanent": "true"}
    )
    assert resp.status_code == 204

    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 404
    assert (await client.post(f"/api/v1/documents/{doc['id']}/restore")).status_code == 404
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0
    versions = await client.get(f"/api/v1/documents/{doc['id']}/versions")
    assert versions.status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_unknown_document_is_404(client: AsyncClient):
    resp = await client.delete(
        f"/api/v1/documents/{uuid.uuid4()}", params={"permanent": "true"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_default_delete_still_soft_deletes(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id, "Soft")
    resp = await client.delete(f"/api/v1/documents/{doc['id']}", params={"permanent": "false"})
    assert resp.status_code == 204
    trash = await client.get("/api/v1/documents/trash")
    assert [item["id"] for item in trash.json()["items"]] == [doc["id"]]
