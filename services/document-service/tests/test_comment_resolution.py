"""Tests for comment resolution endpoints and service methods."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.document import CommentCreate, DocumentCreate
from app.services.document_service import DocumentService
from app.services.event_publisher import event_publisher


async def _create_doc_with_comment(
    client: AsyncClient, owner_id: uuid.UUID, author_id: uuid.UUID
) -> tuple[str, str]:
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]
    comment_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(author_id), "content": "Needs review"},
    )
    return doc_id, comment_resp.json()["id"]


@pytest.mark.asyncio
async def test_resolve_comment(client: AsyncClient, owner_id: uuid.UUID):
    author_id = uuid.uuid4()
    doc_id, comment_id = await _create_doc_with_comment(client, owner_id, author_id)
    resolver_id = str(uuid.uuid4())

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_id}/resolve",
        json={"resolved_by": resolver_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_resolved"] is True
    assert data["resolved_by"] == resolver_id
    assert data["resolved_at"] is not None


@pytest.mark.asyncio
async def test_resolve_comment_not_found(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{uuid.uuid4()}/resolve",
        json={"resolved_by": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unresolve_comment(client: AsyncClient, owner_id: uuid.UUID):
    author_id = uuid.uuid4()
    doc_id, comment_id = await _create_doc_with_comment(client, owner_id, author_id)

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
async def test_unresolve_comment_not_found(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments/{uuid.uuid4()}/unresolve"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_comments_include_resolved_filter(
    client: AsyncClient, owner_id: uuid.UUID
):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    comment_ids = []
    for i in range(3):
        resp = await client.post(
            f"/api/v1/documents/{doc_id}/comments",
            json={"author_id": str(uuid.uuid4()), "content": f"Comment {i}"},
        )
        comment_ids.append(resp.json()["id"])

    await client.post(
        f"/api/v1/documents/{doc_id}/comments/{comment_ids[0]}/resolve",
        json={"resolved_by": str(uuid.uuid4())},
    )

    resp = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert resp.status_code == 200
    assert len(resp.json()) == 3

    resp = await client.get(
        f"/api/v1/documents/{doc_id}/comments",
        params={"include_resolved": "false"},
    )
    assert resp.status_code == 200
    unresolved = resp.json()
    assert len(unresolved) == 2
    assert comment_ids[0] not in [c["id"] for c in unresolved]


@pytest.mark.asyncio
async def test_service_resolve_comment_publishes_event(
    db_session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
):
    events: list[tuple[str, dict]] = []

    async def _capture(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(event_publisher, "publish", _capture)

    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="Doc", content="", owner_id=owner_id)
    )
    author_id = uuid.uuid4()
    comment = await service.add_comment(
        doc.id, CommentCreate(author_id=author_id, content="Needs review")
    )
    assert comment is not None

    resolver_id = uuid.uuid4()
    resolved = await service.resolve_comment(doc.id, comment.id, resolver_id)
    assert resolved is not None
    assert resolved.is_resolved is True
    assert resolved.resolved_by == resolver_id
    assert resolved.resolved_at is not None

    event_type, payload = events[-1]
    assert event_type == "comment_resolved"
    assert payload["documentId"] == doc.id
    assert payload["commentId"] == comment.id
    assert payload["resolvedBy"] == resolver_id
    assert payload["authorId"] == author_id
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_service_unresolve_comment(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="Doc", content="", owner_id=owner_id)
    )
    comment = await service.add_comment(
        doc.id, CommentCreate(author_id=uuid.uuid4(), content="Needs review")
    )
    assert comment is not None

    await service.resolve_comment(doc.id, comment.id, uuid.uuid4())
    unresolved = await service.unresolve_comment(doc.id, comment.id)
    assert unresolved is not None
    assert unresolved.is_resolved is False
    assert unresolved.resolved_by is None
    assert unresolved.resolved_at is None


@pytest.mark.asyncio
async def test_service_resolve_comment_not_found(db_session: AsyncSession):
    service = DocumentService(db_session)
    assert await service.resolve_comment(uuid.uuid4(), uuid.uuid4(), uuid.uuid4()) is None
    assert await service.unresolve_comment(uuid.uuid4(), uuid.uuid4()) is None
