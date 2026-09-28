"""Tests for the document trash lifecycle: list, restore, permanent delete."""

import os
import uuid

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Comment, DocumentVersion
from app.schemas.document import CommentCreate, DocumentCreate, DocumentUpdate
from app.services.document_service import DocumentService

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105
os.environ.setdefault("JWT_SECRET", TEST_JWT_SECRET)


def _auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    token = jwt.encode({"user_id": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _create(client: AsyncClient, title: str = "Doc") -> str:
    resp = await client.post("/api/v1/documents/", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---- Service layer ----


@pytest.mark.asyncio
async def test_delete_stamps_deleted_at_and_lists_in_trash(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="Trashed", content="body", owner_id=owner_id)
    )
    await service.delete(doc.id)

    items, total = await service.list_trashed(owner_id=owner_id)
    assert total == 1
    assert items[0].id == doc.id
    assert items[0].deleted_at is not None

    live, live_total = await service.list_documents(owner_id=owner_id)
    assert live_total == 0
    assert live == []


@pytest.mark.asyncio
async def test_list_trashed_excludes_other_owners(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    other_owner = uuid.uuid4()
    mine = await service.create(DocumentCreate(title="Mine", owner_id=owner_id))
    theirs = await service.create(DocumentCreate(title="Theirs", owner_id=other_owner))
    await service.delete(mine.id)
    await service.delete(theirs.id)

    items, total = await service.list_trashed(owner_id=owner_id)
    assert total == 1
    assert [item.id for item in items] == [mine.id]


@pytest.mark.asyncio
async def test_restore_clears_deleted_state_and_keeps_versions(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="Restore me", content="first", owner_id=owner_id)
    )
    await service.update(doc.id, DocumentUpdate(title="Restore me", content="second"))
    await service.delete(doc.id)

    restored = await service.restore(doc.id)
    assert restored is not None
    assert restored.is_deleted is False
    assert restored.deleted_at is None
    assert restored.content == "second"
    assert [v.version_number for v in await service.list_versions(doc.id)] == [2, 1]

    assert await service.get(doc.id) is not None
    assert await service.restore(doc.id) is None


@pytest.mark.asyncio
async def test_purge_removes_document_versions_and_comments(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="Purge me", content="body", owner_id=owner_id)
    )
    await service.add_comment(
        doc.id, CommentCreate(author_id=owner_id, content="a comment")
    )

    assert await service.purge(doc.id) is False  # still live

    await service.delete(doc.id)
    assert await service.purge(doc.id) is True

    assert await service.get_deleted(doc.id) is None
    versions = await db_session.execute(
        select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
    )
    comments = await db_session.execute(
        select(Comment).where(Comment.document_id == doc.id)
    )
    assert versions.scalars().all() == []
    assert comments.scalars().all() == []


# ---- API layer ----


@pytest.mark.asyncio
async def test_trash_route_is_not_swallowed_by_document_id(client: AsyncClient):
    doc_id = await _create(client, "Routing")
    await client.delete(f"/api/v1/documents/{doc_id}")

    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == doc_id
    assert body["items"][0]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_trash_list_is_paginated_newest_first(client: AsyncClient):
    ids = [await _create(client, f"Doc {i}") for i in range(3)]
    for doc_id in ids:
        await client.delete(f"/api/v1/documents/{doc_id}")

    resp = await client.get("/api/v1/documents/trash", params={"page": 1, "size": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_restore_endpoint_round_trip(client: AsyncClient):
    doc_id = await _create(client, "Round trip")
    await client.patch(f"/api/v1/documents/{doc_id}", json={"content": "kept text"})
    await client.delete(f"/api/v1/documents/{doc_id}")
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404

    resp = await client.post(f"/api/v1/documents/{doc_id}/restore")
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_deleted"] is False
    assert resp.json()["content"] == "kept text"

    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 200
    versions = await client.get(f"/api/v1/documents/{doc_id}/versions")
    assert [v["version_number"] for v in versions.json()] == [2, 1]
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_unknown_or_live_document_returns_404(client: AsyncClient):
    assert (
        await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")
    ).status_code == 404

    doc_id = await _create(client, "Still live")
    assert (
        await client.post(f"/api/v1/documents/{doc_id}/restore")
    ).status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_requires_a_trashed_document(client: AsyncClient):
    doc_id = await _create(client, "Permanent")

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}", params={"permanent": "true"}
    )
    assert resp.status_code == 404
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 200

    await client.delete(f"/api/v1/documents/{doc_id}")
    resp = await client.delete(
        f"/api/v1/documents/{doc_id}", params={"permanent": "true"}
    )
    assert resp.status_code == 204
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0
    assert (
        await client.post(f"/api/v1/documents/{doc_id}/restore")
    ).status_code == 404


@pytest.mark.asyncio
async def test_trash_routes_deny_cross_owner_access(client: AsyncClient):
    doc_id = await _create(client, "Owned")
    await client.delete(f"/api/v1/documents/{doc_id}")

    intruder = _auth_headers(uuid.uuid4())

    listing = await client.get("/api/v1/documents/trash", headers=intruder)
    assert listing.status_code == 200
    assert listing.json()["total"] == 0

    assert (
        await client.post(f"/api/v1/documents/{doc_id}/restore", headers=intruder)
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/documents/{doc_id}",
            params={"permanent": "true"},
            headers=intruder,
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_trash_routes_require_authentication(client: AsyncClient):
    assert (await client.get("/api/v1/documents/trash", auth=None)).status_code == 401
    assert (
        await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore", auth=None)
    ).status_code == 401
