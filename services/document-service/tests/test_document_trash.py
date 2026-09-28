"""Tests for the document trash lifecycle: trash listing, restore, purge."""

import os
import uuid

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Comment, Document, DocumentVersion
from app.schemas.document import CommentCreate, DocumentCreate
from app.services.document_service import DocumentService

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105
os.environ.setdefault("JWT_SECRET", TEST_JWT_SECRET)


def _other_user_headers() -> dict[str, str]:
    token = jwt.encode(
        {"user_id": str(uuid.uuid4())}, TEST_JWT_SECRET, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_document(client: AsyncClient, owner_id: uuid.UUID, title: str) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": title, "content": "body text", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_deleted_document_appears_in_trash(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Trashable")

    assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204

    listed = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert all(item["id"] != doc_id for item in listed.json()["items"])

    trash = await client.get("/api/v1/documents/trash")
    assert trash.status_code == 200
    body = trash.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == doc_id
    assert body["items"][0]["is_deleted"] is True
    assert body["items"][0]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_trash_is_paginated_newest_first(
    client: AsyncClient, owner_id: uuid.UUID, db_session: AsyncSession
):
    ids = [await _create_document(client, owner_id, f"Doc {i}") for i in range(3)]
    for doc_id in ids:
        await client.delete(f"/api/v1/documents/{doc_id}")

    first = await client.get("/api/v1/documents/trash", params={"page": 1, "size": 2})
    assert first.json()["total"] == 3
    assert first.json()["pages"] == 2
    assert len(first.json()["items"]) == 2
    second = await client.get("/api/v1/documents/trash", params={"page": 2, "size": 2})
    assert len(second.json()["items"]) == 1

    returned = [item["id"] for item in first.json()["items"]] + [
        item["id"] for item in second.json()["items"]
    ]
    deleted_at = {}
    for doc_id in returned:
        row = (
            await db_session.execute(
                select(Document).where(Document.id == uuid.UUID(doc_id))
            )
        ).scalar_one()
        deleted_at[doc_id] = row.deleted_at
    assert returned == sorted(returned, key=lambda i: deleted_at[i], reverse=True)


@pytest.mark.asyncio
async def test_trash_excludes_live_and_other_owners_documents(
    client: AsyncClient, owner_id: uuid.UUID, db_session: AsyncSession
):
    live_id = await _create_document(client, owner_id, "Still here")
    mine_id = await _create_document(client, owner_id, "Mine")
    await client.delete(f"/api/v1/documents/{mine_id}")

    other_owner = uuid.uuid4()
    theirs = await DocumentService(db_session).create(
        DocumentCreate(title="Theirs", content="secret", owner_id=other_owner)
    )
    await DocumentService(db_session).delete(theirs.id)

    trash = await client.get("/api/v1/documents/trash")
    ids = [item["id"] for item in trash.json()["items"]]
    assert ids == [mine_id]
    assert live_id not in ids
    assert str(theirs.id) not in ids


@pytest.mark.asyncio
async def test_trash_requires_authentication(client: AsyncClient):
    resp = await client.get("/api/v1/documents/trash", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_restore_brings_back_content_and_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Round trip")
    await client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Round trip v2", "content": "second revision"},
    )
    await client.delete(f"/api/v1/documents/{doc_id}")

    restore = await client.post(f"/api/v1/documents/{doc_id}/restore")
    assert restore.status_code == 200, restore.text
    restored = restore.json()
    assert restored["is_deleted"] is False
    assert restored["deleted_at"] is None
    assert restored["content"] == "second revision"

    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 200
    versions = await client.get(f"/api/v1/documents/{doc_id}/versions")
    assert [v["version_number"] for v in versions.json()] == [2, 1]

    trash = await client.get("/api/v1/documents/trash")
    assert trash.json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_unknown_or_live_document_is_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    assert (
        await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")
    ).status_code == 404

    live_id = await _create_document(client, owner_id, "Live")
    assert (
        await client.post(f"/api/v1/documents/{live_id}/restore")
    ).status_code == 404


@pytest.mark.asyncio
async def test_restore_denied_for_other_owner(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id, "Private")
    await client.delete(f"/api/v1/documents/{doc_id}")

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/restore", headers=_other_user_headers()
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_permanent_delete_removes_document_versions_and_comments(
    client: AsyncClient, owner_id: uuid.UUID, db_session: AsyncSession
):
    doc_id = await _create_document(client, owner_id, "Purge me")
    await DocumentService(db_session).add_comment(
        uuid.UUID(doc_id), CommentCreate(author_id=owner_id, content="a note")
    )
    await client.delete(f"/api/v1/documents/{doc_id}")

    purge = await client.delete(
        f"/api/v1/documents/{doc_id}", params={"permanent": "true"}
    )
    assert purge.status_code == 204, purge.text

    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404
    for model in (Document, DocumentVersion, Comment):
        column = model.id if model is Document else model.document_id
        rows = (
            await db_session.execute(select(model).where(column == uuid.UUID(doc_id)))
        ).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_permanent_delete_requires_a_trashed_document(
    client: AsyncClient, owner_id: uuid.UUID
):
    live_id = await _create_document(client, owner_id, "Live")
    resp = await client.delete(
        f"/api/v1/documents/{live_id}", params={"permanent": "true"}
    )
    assert resp.status_code == 404
    assert (await client.get(f"/api/v1/documents/{live_id}")).status_code == 200


@pytest.mark.asyncio
async def test_permanent_delete_denied_for_other_owner(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Private")
    await client.delete(f"/api/v1/documents/{doc_id}")

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}",
        params={"permanent": "true"},
        headers=_other_user_headers(),
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_default_delete_stays_a_soft_delete(
    client: AsyncClient, owner_id: uuid.UUID, db_session: AsyncSession
):
    doc_id = await _create_document(client, owner_id, "Soft")
    await client.delete(f"/api/v1/documents/{doc_id}")

    row = (
        await db_session.execute(
            select(Document).where(Document.id == uuid.UUID(doc_id))
        )
    ).scalar_one()
    assert row.is_deleted is True
    assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_service_restore_and_purge_publish_events(
    db_session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
):
    published: list[str] = []

    async def _capture(event_type: str, payload: dict) -> None:
        published.append(event_type)

    monkeypatch.setattr(
        "app.services.document_service.event_publisher.publish", _capture
    )

    service = DocumentService(db_session)
    document = await service.create(
        DocumentCreate(title="Events", content="body", owner_id=owner_id)
    )
    await service.delete(document.id)
    assert await service.restore(document.id) is not None
    await service.delete(document.id)
    assert await service.purge(document.id) is True
    assert await service.purge(document.id) is False

    assert published == [
        "document_created",
        "document_deleted",
        "document_restored",
        "document_deleted",
        "document_purged",
    ]
