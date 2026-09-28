"""Tests for the document trash: listing, restore and permanent delete."""

import uuid

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from tests.conftest import TEST_JWT_SECRET


def _other_owner_headers(user_id: uuid.UUID) -> dict[str, str]:
    token = jwt.encode({"user_id": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _create_document(
    client: AsyncClient, owner_id: uuid.UUID, title: str = "Doc", content: str = "Body"
) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": title, "content": content, "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_trash_lists_only_deleted_documents(
    client: AsyncClient, owner_id: uuid.UUID
):
    kept_id = await _create_document(client, owner_id, title="Kept")
    deleted_id = await _create_document(client, owner_id, title="Deleted")

    assert (await client.delete(f"/api/v1/documents/{deleted_id}")).status_code == 204

    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == [deleted_id]
    assert data["items"][0]["is_deleted"] is True
    assert data["items"][0]["deleted_at"] is not None

    listing = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert [item["id"] for item in listing.json()["items"]] == [kept_id]


@pytest.mark.asyncio
async def test_trash_excludes_templates(
    client: AsyncClient, db_session: AsyncSession, owner_id: uuid.UUID
):
    template_id = await _create_document(client, owner_id, title="Template")
    await db_session.execute(
        update(Document)
        .where(Document.id == uuid.UUID(template_id))
        .values(is_template=True)
    )
    await db_session.commit()
    await client.delete(f"/api/v1/documents/{template_id}")

    trash = await client.get("/api/v1/documents/trash")
    assert trash.json()["total"] == 0


@pytest.mark.asyncio
async def test_trash_does_not_leak_other_owners(
    client: AsyncClient, owner_id: uuid.UUID
):
    document_id = await _create_document(client, owner_id)
    await client.delete(f"/api/v1/documents/{document_id}")

    other = uuid.uuid4()
    resp = await client.get(
        "/api/v1/documents/trash", headers=_other_owner_headers(other)
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_trash_requires_authentication(client: AsyncClient):
    resp = await client.get("/api/v1/documents/trash", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trash_pagination(client: AsyncClient, owner_id: uuid.UUID):
    for i in range(3):
        doc_id = await _create_document(client, owner_id, title=f"Doc {i}")
        await client.delete(f"/api/v1/documents/{doc_id}")

    resp = await client.get("/api/v1/documents/trash", params={"page": 1, "size": 2})
    data = resp.json()
    assert data["total"] == 3
    assert data["pages"] == 2
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_restore_brings_document_back_with_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    document_id = await _create_document(client, owner_id, content="First revision")
    update_resp = await client.put(
        f"/api/v1/documents/{document_id}",
        json={"title": "Doc", "content": "Second revision"},
    )
    assert update_resp.status_code == 200, update_resp.text
    await client.delete(f"/api/v1/documents/{document_id}")

    resp = await client.post(f"/api/v1/documents/{document_id}/restore")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == document_id
    assert body["is_deleted"] is False
    assert body["content"] == "Second revision"

    get_resp = await client.get(f"/api/v1/documents/{document_id}")
    assert get_resp.status_code == 200

    versions = await client.get(f"/api/v1/documents/{document_id}/versions")
    assert versions.status_code == 200
    assert len(versions.json()) >= 1

    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_unknown_or_live_document_returns_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    live_id = await _create_document(client, owner_id)

    assert (
        await client.post(f"/api/v1/documents/{live_id}/restore")
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")
    ).status_code == 404


@pytest.mark.asyncio
async def test_restore_denied_for_other_owner(client: AsyncClient, owner_id: uuid.UUID):
    document_id = await _create_document(client, owner_id)
    await client.delete(f"/api/v1/documents/{document_id}")

    resp = await client.post(
        f"/api/v1/documents/{document_id}/restore",
        headers=_other_owner_headers(uuid.uuid4()),
    )
    assert resp.status_code == 403

    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_permanent_delete_removes_document(
    client: AsyncClient, owner_id: uuid.UUID
):
    document_id = await _create_document(client, owner_id)
    await client.post(
        f"/api/v1/documents/{document_id}/comments",
        json={"content": "A comment", "author_id": str(owner_id)},
    )
    await client.delete(f"/api/v1/documents/{document_id}")

    resp = await client.delete(
        f"/api/v1/documents/{document_id}", params={"permanent": True}
    )
    assert resp.status_code == 204

    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0
    assert (
        await client.post(f"/api/v1/documents/{document_id}/restore")
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/documents/{document_id}", params={"permanent": True}
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_requires_soft_delete_first(
    client: AsyncClient, owner_id: uuid.UUID
):
    document_id = await _create_document(client, owner_id)

    resp = await client.delete(
        f"/api/v1/documents/{document_id}", params={"permanent": True}
    )
    assert resp.status_code == 404
    assert (await client.get(f"/api/v1/documents/{document_id}")).status_code == 200


@pytest.mark.asyncio
async def test_permanent_delete_denied_for_other_owner(
    client: AsyncClient, owner_id: uuid.UUID
):
    document_id = await _create_document(client, owner_id)
    await client.delete(f"/api/v1/documents/{document_id}")

    resp = await client.delete(
        f"/api/v1/documents/{document_id}",
        params={"permanent": True},
        headers=_other_owner_headers(uuid.uuid4()),
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1


@pytest.mark.asyncio
async def test_default_delete_stays_soft(client: AsyncClient, owner_id: uuid.UUID):
    document_id = await _create_document(client, owner_id)

    assert (await client.delete(f"/api/v1/documents/{document_id}")).status_code == 204
    assert (await client.get(f"/api/v1/documents/{document_id}")).status_code == 404
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1
    assert (
        await client.post(f"/api/v1/documents/{document_id}/restore")
    ).status_code == 200
