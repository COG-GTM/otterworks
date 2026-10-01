"""Degraded-health and template/comment API edge cases."""

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.health import health, metrics
from app.db.session import get_db
from app.main import app
from app.schemas.document import DocumentPatch


class _FailingSession:
    async def execute(self, *args, **kwargs):
        raise ConnectionRefusedError("postgres unreachable")


@pytest.mark.asyncio
async def test_health_reports_healthy_when_db_responds(db_session: AsyncSession):
    body = await health(db=db_session)

    assert body == {
        "status": "healthy",
        "service": "document-service",
        "checks": {"database": "connected"},
    }


@pytest.mark.asyncio
async def test_metrics_exposes_the_up_gauge():
    body = await metrics()

    assert "document_service_up 1" in body
    assert body.startswith("# HELP")


@pytest.mark.parametrize("field", ["title", "content", "content_type"])
def test_document_patch_rejects_explicit_nulls(field):
    with pytest.raises(ValidationError) as exc:
        DocumentPatch(**{field: None})

    assert f"{field} cannot be null" in str(exc.value)


def test_document_patch_allows_clearing_folder_id():
    assert DocumentPatch(folder_id=None).folder_id is None


@pytest.mark.asyncio
async def test_health_reports_degraded_when_db_is_unreachable():
    body = await health(db=_FailingSession())

    assert body == {
        "status": "degraded",
        "service": "document-service",
        "checks": {"database": "disconnected"},
    }


@pytest.mark.asyncio
async def test_health_endpoint_reports_degraded_through_the_app(client: AsyncClient):
    async def _override_get_db():
        yield _FailingSession()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        resp = await client.get("/health")
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous

    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"


@pytest.mark.asyncio
async def test_create_template_returns_created_payload(client: AsyncClient, owner_id: uuid.UUID):
    resp = await client.post(
        "/api/v1/templates/",
        json={
            "name": "Meeting notes",
            "description": "Standard agenda",
            "content": "# Agenda",
            "created_by": str(owner_id),
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Meeting notes"
    assert body["content"] == "# Agenda"

    listed = await client.get("/api/v1/templates/")
    assert [t["name"] for t in listed.json()] == ["Meeting notes"]


@pytest.mark.asyncio
async def test_list_comments_returns_comments_in_creation_order(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = (
        await client.post(
            "/api/v1/documents/",
            json={"title": "D", "content": "c", "owner_id": str(owner_id)},
        )
    ).json()
    for text in ("first", "second"):
        resp = await client.post(
            f"/api/v1/documents/{doc['id']}/comments",
            json={"author_id": str(owner_id), "content": text},
        )
        assert resp.status_code == 201

    listed = await client.get(f"/api/v1/documents/{doc['id']}/comments")

    assert listed.status_code == 200
    assert [c["content"] for c in listed.json()] == ["first", "second"]


@pytest.mark.asyncio
async def test_list_comments_of_unknown_document_is_empty(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}/comments")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_delete_comment_removes_it(client: AsyncClient, owner_id: uuid.UUID):
    doc = (
        await client.post(
            "/api/v1/documents/",
            json={"title": "D", "content": "c", "owner_id": str(owner_id)},
        )
    ).json()
    comment = (
        await client.post(
            f"/api/v1/documents/{doc['id']}/comments",
            json={"author_id": str(owner_id), "content": "remove me"},
        )
    ).json()

    resp = await client.delete(f"/api/v1/documents/{doc['id']}/comments/{comment['id']}")

    assert resp.status_code == 204
    remaining = await client.get(f"/api/v1/documents/{doc['id']}/comments")
    assert remaining.json() == []
