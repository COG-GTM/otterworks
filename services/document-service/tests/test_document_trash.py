"""Tests for the document trash lifecycle: listing, restore, and purge."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.document import Comment, DocumentVersion
from app.schemas.document import CommentCreate, DocumentCreate
from app.services.document_service import DocumentService
from tests.conftest import bearer_auth


async def _create_document(client: AsyncClient, owner_id: uuid.UUID, title: str) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": title, "content": "trash body", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def other_client(db_session: AsyncSession):
    """Client authenticated as a user who owns nothing."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", auth=bearer_auth(uuid.uuid4())
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_deleted_document_appears_in_trash(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Doomed")

    empty = await client.get("/api/v1/documents/trash")
    assert empty.status_code == 200
    assert empty.json()["total"] == 0

    assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204

    trash = await client.get("/api/v1/documents/trash")
    assert trash.status_code == 200
    body = trash.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == doc_id
    assert body["items"][0]["is_deleted"] is True
    assert body["items"][0]["deleted_at"] is not None

    listing = await client.get("/api/v1/documents/")
    assert all(item["id"] != doc_id for item in listing.json()["items"])


@pytest.mark.asyncio
async def test_trash_is_paginated_newest_first(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_ids = [await _create_document(client, owner_id, f"Doc {i}") for i in range(3)]
    for doc_id in doc_ids:
        await client.delete(f"/api/v1/documents/{doc_id}")

    page = await client.get("/api/v1/documents/trash", params={"page": 1, "size": 2})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] == doc_ids[-1]


@pytest.mark.asyncio
async def test_trash_excludes_other_owners(
    client: AsyncClient, other_client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Private")
    await client.delete(f"/api/v1/documents/{doc_id}")

    trash = await other_client.get("/api/v1/documents/trash")
    assert trash.status_code == 200
    assert trash.json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_brings_document_back_with_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Restorable")
    await client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Restorable v2", "content": "second body"},
    )
    await client.delete(f"/api/v1/documents/{doc_id}")

    restored = await client.post(f"/api/v1/documents/{doc_id}/restore")
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["is_deleted"] is False
    assert body["deleted_at"] is None
    assert body["content"] == "second body"

    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 200
    versions = await client.get(f"/api/v1/documents/{doc_id}/versions")
    assert [v["version_number"] for v in versions.json()] == [2, 1]
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_unknown_or_live_document_is_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    unknown = await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")
    assert unknown.status_code == 404

    doc_id = await _create_document(client, owner_id, "Still alive")
    live = await client.post(f"/api/v1/documents/{doc_id}/restore")
    assert live.status_code == 404


@pytest.mark.asyncio
async def test_restore_denied_for_other_owner(
    client: AsyncClient, other_client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Not yours")
    await client.delete(f"/api/v1/documents/{doc_id}")

    denied = await other_client.post(f"/api/v1/documents/{doc_id}/restore")
    assert denied.status_code == 403

    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_permanent_delete_removes_document_versions_and_comments(
    client: AsyncClient, db_session: AsyncSession, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Purge me")
    await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(owner_id), "content": "bye"},
    )
    await client.delete(f"/api/v1/documents/{doc_id}")

    purged = await client.delete(
        f"/api/v1/documents/{doc_id}", params={"permanent": "true"}
    )
    assert purged.status_code == 204, purged.text

    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0
    assert (await client.post(f"/api/v1/documents/{doc_id}/restore")).status_code == 404

    versions = await db_session.execute(
        select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(doc_id))
    )
    assert versions.scalars().all() == []
    comments = await db_session.execute(
        select(Comment).where(Comment.document_id == uuid.UUID(doc_id))
    )
    assert comments.scalars().all() == []


@pytest.mark.asyncio
async def test_permanent_delete_denied_for_other_owner(
    client: AsyncClient, other_client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Guarded")
    await client.delete(f"/api/v1/documents/{doc_id}")

    denied = await other_client.delete(
        f"/api/v1/documents/{doc_id}", params={"permanent": "true"}
    )
    assert denied.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_permanent_delete_requires_a_trashed_document(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id, "Still live")

    rejected = await client.delete(
        f"/api/v1/documents/{doc_id}", params={"permanent": "true"}
    )
    assert rejected.status_code == 404
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 200


@pytest.mark.asyncio
async def test_delete_defaults_to_soft_delete(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id, "Soft only")
    assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_trash_route_is_not_swallowed_by_document_id(client: AsyncClient):
    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200
    assert "items" in resp.json()


@pytest.mark.asyncio
async def test_service_restore_and_purge(db_session: AsyncSession, owner_id: uuid.UUID):
    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="Service trash", content="body", owner_id=owner_id)
    )
    await service.add_comment(
        doc.id, CommentCreate(author_id=owner_id, content="note")
    )

    assert await service.delete(doc.id) is True
    assert await service.get(doc.id) is None
    trashed, total = await service.list_trashed(owner_id=owner_id)
    assert total == 1
    assert trashed[0].id == doc.id

    restored = await service.restore(doc.id)
    assert restored is not None
    assert restored.is_deleted is False
    assert await service.restore(doc.id) is None

    assert await service.purge(doc.id) is True
    assert await service.get(doc.id) is None
    assert await service.purge(doc.id) is False
