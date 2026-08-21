"""Tests for comment API endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_add_comment(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Commented Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]
    author_id = str(uuid.uuid4())

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": author_id, "content": "Great document!"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Great document!"
    assert data["author_id"] == author_id
    assert data["document_id"] == doc_id


@pytest.mark.asyncio
async def test_add_comment_document_not_found(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/documents/{uuid.uuid4()}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "Orphan comment"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_comments(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    for i in range(3):
        await client.post(
            f"/api/v1/documents/{doc_id}/comments",
            json={"author_id": str(uuid.uuid4()), "content": f"Comment {i}"},
        )

    resp = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_delete_comment(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    comment_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "To delete"},
    )
    comment_id = comment_resp.json()["id"]

    resp = await client.delete(f"/api/v1/documents/{doc_id}/comments/{comment_id}")
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_delete_comment_not_found(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}/comments/{uuid.uuid4()}"
    )
    assert resp.status_code == 404


async def _create_comment(
    client: AsyncClient, owner_id: uuid.UUID, author_id: uuid.UUID | None = None
) -> tuple[str, str]:
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]
    author = author_id or uuid.uuid4()
    comment_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(author), "content": "A comment"},
    )
    return doc_id, comment_resp.json()["id"]


@pytest.mark.asyncio
async def test_resolve_and_unresolve_comment(client: AsyncClient, owner_id: uuid.UUID):
    doc_id, comment_id = await _create_comment(client, owner_id)

    resolved = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve"
    )
    assert resolved.status_code == 200
    assert resolved.json()["is_resolved"] is True
    assert resolved.json()["resolved_by"] == str(owner_id)
    assert resolved.json()["resolved_at"] is not None

    unresolved = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/unresolve"
    )
    assert unresolved.status_code == 200
    assert unresolved.json()["is_resolved"] is False
    assert unresolved.json()["resolved_by"] is None
    assert unresolved.json()["resolved_at"] is None


@pytest.mark.asyncio
async def test_resolve_comment_is_idempotent(client: AsyncClient, owner_id: uuid.UUID):
    doc_id, comment_id = await _create_comment(client, owner_id)

    first = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve"
    )
    second = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve"
    )
    assert first.status_code == second.status_code == 200
    assert second.json()["resolved_by"] == str(owner_id)
    assert second.json()["resolved_at"] == first.json()["resolved_at"]


@pytest.mark.asyncio
async def test_resolve_comment_not_found(client: AsyncClient, owner_id: uuid.UUID):
    doc_id, _ = await _create_comment(client, owner_id)
    response = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{uuid.uuid4()}/resolve"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolved_comment_filter_and_unauthenticated(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id, comment_id = await _create_comment(client, owner_id)
    await client.post(f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve")

    hidden = await client.get(
        f"/api/v1/documents/{doc_id}/comments?include_resolved=false"
    )
    included = await client.get(
        f"/api/v1/documents/{doc_id}/comments?include_resolved=true"
    )
    default = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert hidden.json() == []
    assert len(included.json()) == len(default.json()) == 1

    unauthenticated = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve", auth=None
    )
    assert unauthenticated.status_code == 401


@pytest.mark.asyncio
async def test_comment_resolved_event_targets_author(
    client: AsyncClient, owner_id: uuid.UUID
):
    author_id = uuid.uuid4()
    doc_id, comment_id = await _create_comment(client, owner_id, author_id)
    with patch(
        "app.services.document_service.event_publisher.publish",
        new_callable=AsyncMock,
    ) as publish:
        response = await client.post(
            f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve"
        )

    assert response.status_code == 200
    publish.assert_awaited_once()
    event_type, payload = publish.await_args.args
    assert event_type == "comment_resolved"
    assert payload["author_id"] == author_id
    assert payload["resolved_by"] == owner_id


@pytest.mark.asyncio
async def test_comment_resolved_event_not_published_for_author(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id, comment_id = await _create_comment(client, owner_id, owner_id)
    with patch(
        "app.services.document_service.event_publisher.publish",
        new_callable=AsyncMock,
    ) as publish:
        response = await client.post(
            f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve"
        )

    assert response.status_code == 200
    publish.assert_not_awaited()
