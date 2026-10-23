"""Tests for the document list endpoint's metadata filters.

Requests are sent unauthenticated (``auth=None``): the filter path scopes by
the JWT-derived owner, and these tests exercise the unscoped upstream
semantics.
"""

import uuid

import pytest
from httpx import AsyncClient


async def _create(client: AsyncClient, owner_id: uuid.UUID, title: str, **kwargs):
    payload = {"title": title, "content": "body", "owner_id": str(owner_id)}
    payload.update(kwargs)
    resp = await client.post("/api/v1/documents/", json=payload, auth=None)
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_filter_by_title_fragment(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Quarterly Report")
    await _create(client, owner_id, "Meeting Notes")

    resp = await client.get("/api/v1/documents/", params={"title": "report"}, auth=None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["Quarterly Report"]


@pytest.mark.asyncio
async def test_filter_by_content_type(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Plan", content_type="text/markdown")
    await _create(client, owner_id, "Page", content_type="text/html")

    resp = await client.get(
        "/api/v1/documents/", params={"content_type": "text/html"}, auth=None
    )

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Page"]


@pytest.mark.asyncio
async def test_filter_orders_by_title_ascending(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Beta plan")
    await _create(client, owner_id, "Alpha plan")

    resp = await client.get(
        "/api/v1/documents/",
        params={"title": "plan", "sort": "title", "direction": "asc"},
        auth=None,
    )

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Alpha plan", "Beta plan"]


@pytest.mark.asyncio
async def test_filter_paginates(client: AsyncClient, owner_id: uuid.UUID):
    for index in range(3):
        await _create(client, owner_id, f"Plan {index}")

    resp = await client.get(
        "/api/v1/documents/", params={"title": "plan", "size": 2, "page": 2}, auth=None
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_filter_no_match_returns_empty(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get("/api/v1/documents/", params={"title": "nothing"}, auth=None)

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "size": 20, "pages": 1}


@pytest.mark.asyncio
async def test_unfiltered_list_is_unchanged(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id)}, auth=None
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_title_quote_is_matched_literally(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get(
        "/api/v1/documents/",
        params={"owner_id": str(owner_id), "title": "report'"},
        auth=None,
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_title_union_injection_returns_no_rows(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get(
        "/api/v1/documents/",
        params={
            "owner_id": str(owner_id),
            "title": "x%') UNION SELECT id, title, content, content_type, owner_id, folder_id, "
            "is_deleted, is_template, word_count, version, created_at, updated_at "
            "FROM documents--",
        },
        auth=None,
    )

    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_content_type_tautology_does_not_cross_owners(
    client: AsyncClient, owner_id: uuid.UUID
):
    other_owner = uuid.uuid4()
    await _create(client, owner_id, "Mine", content_type="text/markdown")
    await _create(client, other_owner, "Theirs", content_type="text/html")

    resp = await client.get(
        "/api/v1/documents/",
        params={"owner_id": str(owner_id), "content_type": "text/markdown' OR '1'='1"},
        auth=None,
    )

    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"sort": "title; DROP TABLE documents"},
        {"sort": "(SELECT 1)"},
        {"sort": "title", "direction": "desc; DROP TABLE documents"},
    ],
)
async def test_sort_outside_allow_list_is_rejected(
    client: AsyncClient, owner_id: uuid.UUID, params: dict[str, str]
):
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id), **params}, auth=None
    )

    assert resp.status_code == 400
    assert "DROP" not in resp.text
    assert "SELECT" not in resp.text
    follow_up = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id), "title": "report"}, auth=None
    )
    assert follow_up.json()["total"] == 1


@pytest.mark.asyncio
async def test_direction_is_case_insensitive(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Beta plan")
    await _create(client, owner_id, "Alpha plan")

    resp = await client.get(
        "/api/v1/documents/",
        params={"owner_id": str(owner_id), "sort": "title", "direction": "ASC"},
        auth=None,
    )

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Alpha plan", "Beta plan"]


@pytest.mark.asyncio
async def test_database_errors_are_not_reflected(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
):
    from sqlalchemy.exc import OperationalError

    from app.services.document_query_repository import DocumentQueryRepository

    async def _boom(self, **kwargs):
        raise OperationalError("SELECT secret FROM documents", {}, Exception("syntax error"))

    monkeypatch.setattr(DocumentQueryRepository, "count_documents", _boom)

    resp = await client.get("/api/v1/documents/", params={"title": "report"}, auth=None)

    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid filter"}
