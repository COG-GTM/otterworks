"""Tests for comment API endpoints."""

import uuid
from unittest.mock import AsyncMock

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
async def test_resolve_comment_sets_fields_and_publishes_event(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]
    author_id = uuid.uuid4()
    comment_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(author_id), "content": "Resolve me"},
    )
    comment_id = comment_resp.json()["id"]
    resolved_by = uuid.uuid4()
    publish = AsyncMock()
    monkeypatch.setattr(
        "app.services.document_service.event_publisher.publish", publish
    )

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve",
        json={"resolved_by": str(resolved_by)},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_resolved"] is True
    assert data["resolved_by"] == str(resolved_by)
    assert data["resolved_at"] is not None
    assert publish.await_count == 1
    event_type, payload = publish.await_args.args
    assert event_type == "comment_resolved"
    assert payload["comment_id"] == uuid.UUID(comment_id)
    assert payload["document_id"] == uuid.UUID(doc_id)
    assert payload["author_id"] == author_id
    assert payload["resolved_by"] == resolved_by
    assert payload["resolved_at"] is not None


@pytest.mark.asyncio
async def test_resolve_comment_is_idempotent_and_does_not_republish(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]
    comment_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "Resolve once"},
    )
    comment_id = comment_resp.json()["id"]
    first_resolver = uuid.uuid4()
    second_resolver = uuid.uuid4()
    publish = AsyncMock()
    monkeypatch.setattr(
        "app.services.document_service.event_publisher.publish", publish
    )

    first = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve",
        json={"resolved_by": str(first_resolver)},
    )
    second = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve",
        json={"resolved_by": str(second_resolver)},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert publish.await_count == 1


@pytest.mark.asyncio
async def test_unresolve_comment_clears_fields(
    client: AsyncClient, owner_id: uuid.UUID
):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]
    comment_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "Unresolve me"},
    )
    comment_id = comment_resp.json()["id"]
    await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve",
        json={"resolved_by": str(uuid.uuid4())},
    )

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/unresolve"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_resolved"] is False
    assert data["resolved_by"] is None
    assert data["resolved_at"] is None


@pytest.mark.asyncio
async def test_resolve_comment_not_found_for_unknown_or_other_document(
    client: AsyncClient, owner_id: uuid.UUID
):
    first_doc_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "First", "content": "", "owner_id": str(owner_id)},
    )
    first_doc_id = first_doc_resp.json()["id"]
    second_doc_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Second", "content": "", "owner_id": str(owner_id)},
    )
    second_doc_id = second_doc_resp.json()["id"]
    comment_resp = await client.post(
        f"/api/v1/documents/{first_doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "Wrong document"},
    )
    comment_id = comment_resp.json()["id"]

    unknown_resp = await client.post(
        f"/api/v1/documents/{first_doc_id}/comments/{uuid.uuid4()}/resolve",
        json={"resolved_by": str(uuid.uuid4())},
    )
    other_document_resp = await client.post(
        f"/api/v1/documents/{second_doc_id}/comments/{comment_id}/resolve",
        json={"resolved_by": str(uuid.uuid4())},
    )

    assert unknown_resp.status_code == 404
    assert other_document_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_comments_can_exclude_resolved_comments(
    client: AsyncClient, owner_id: uuid.UUID
):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]
    resolved_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "Resolved"},
    )
    unresolved_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "Unresolved"},
    )
    resolved_id = resolved_resp.json()["id"]
    unresolved_id = unresolved_resp.json()["id"]
    await client.post(
        f"/api/v1/documents/{doc_id}/comments/{resolved_id}/resolve",
        json={"resolved_by": str(uuid.uuid4())},
    )

    default_resp = await client.get(f"/api/v1/documents/{doc_id}/comments")
    filtered_resp = await client.get(
        f"/api/v1/documents/{doc_id}/comments?include_resolved=false"
    )

    assert [comment["id"] for comment in default_resp.json()] == [
        resolved_id,
        unresolved_id,
    ]
    assert [comment["id"] for comment in filtered_resp.json()] == [unresolved_id]


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
