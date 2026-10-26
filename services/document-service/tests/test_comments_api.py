"""Tests for comment API endpoints."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import bearer_auth


async def _create_document(client: AsyncClient, owner_id: uuid.UUID) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Commented Doc", "content": "", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201
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
async def test_add_comment_ignores_body_author_id(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "Spoof attempt"},
    )
    assert resp.status_code == 201
    assert resp.json()["author_id"] == str(owner_id)


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

    resp = await client.delete(f"/api/v1/documents/{doc_id}/comments/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("POST", "", {"content": "anon"}),
        ("DELETE", f"/{uuid.uuid4()}", None),
    ],
)
async def test_comment_routes_require_authentication(
    client: AsyncClient, owner_id: uuid.UUID, method: str, suffix: str, body: dict | None
):
    doc_id = await _create_document(client, owner_id)

    resp = await client.request(
        method, f"/api/v1/documents/{doc_id}/comments{suffix}", json=body, auth=None
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_non_owner_cannot_list_or_add_comments(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)
    await client.post(f"/api/v1/documents/{doc_id}/comments", json={"content": "private"})
    intruder = bearer_auth(uuid.uuid4())

    list_resp = await client.get(f"/api/v1/documents/{doc_id}/comments", auth=intruder)
    assert list_resp.status_code == 403

    add_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(owner_id), "content": "impersonation"},
        auth=intruder,
    )
    assert add_resp.status_code == 403

    owner_view = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert [c["content"] for c in owner_view.json()] == ["private"]


@pytest.mark.asyncio
async def test_non_owner_cannot_delete_comment(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)
    comment_id = (
        await client.post(f"/api/v1/documents/{doc_id}/comments", json={"content": "keep"})
    ).json()["id"]

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}", auth=bearer_auth(uuid.uuid4())
    )
    assert resp.status_code == 403

    owner_view = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert [c["id"] for c in owner_view.json()] == [comment_id]


@pytest.mark.asyncio
async def test_comment_author_can_delete_own_comment(
    client: AsyncClient, db_session, owner_id: uuid.UUID
):
    from app.schemas.document import CommentCreate
    from app.services.document_service import DocumentService

    doc_id = await _create_document(client, owner_id)
    author_id = uuid.uuid4()
    comment = await DocumentService(db_session).add_comment(
        uuid.UUID(doc_id), CommentCreate(content="mine"), author_id=author_id
    )

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}/comments/{comment.id}", auth=bearer_auth(author_id)
    )
    assert resp.status_code == 204
