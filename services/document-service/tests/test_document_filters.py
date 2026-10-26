"""Tests for the document list endpoint's metadata filters.

Requests are sent unauthenticated (``auth=None``): the filter path scopes by
the JWT-derived owner, and these tests exercise the unscoped upstream
semantics.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.services.document_query_repository import DocumentQueryRepository


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
async def test_title_with_quote_is_treated_as_data(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Quarterly Report")
    await _create(client, owner_id, "Owner's Report")

    resp = await client.get(
        "/api/v1/documents/", params={"title": "x%' OR 1=1 --"}, auth=None
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    resp = await client.get("/api/v1/documents/", params={"title": "owner's"}, auth=None)
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Owner's Report"]


@pytest.mark.asyncio
async def test_content_type_tautology_matches_nothing(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Plan", content_type="text/markdown")

    resp = await client.get(
        "/api/v1/documents/",
        params={"content_type": "text/html' OR '1'='1"},
        auth=None,
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"sort": "id;--"},
        {"sort": "title; DROP TABLE documents"},
        {"sort": "(SELECT 1)"},
        {"direction": "desc; SELECT 1"},
        {"direction": "sideways"},
    ],
)
async def test_unsupported_ordering_is_a_generic_400(client: AsyncClient, params: dict):
    resp = await client.get("/api/v1/documents/", params=params, auth=None)

    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid filter"}


@pytest.mark.asyncio
async def test_filter_direction_is_case_insensitive(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Beta plan")
    await _create(client, owner_id, "Alpha plan")

    resp = await client.get(
        "/api/v1/documents/",
        params={"title": "plan", "sort": "title", "direction": "ASC"},
        auth=None,
    )

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Alpha plan", "Beta plan"]


def test_filter_values_are_bound_not_rendered():
    repo = DocumentQueryRepository(db=None)  # type: ignore[arg-type]
    title = "x' OR 1=1 --"
    content_type = "text/html' OR '1'='1"
    owner = "aaaaaaaa-0000-4000-8000-00000000000a"
    stmt = select(func.count()).where(*repo._where(owner, title, content_type))

    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert title not in sql
    assert content_type not in sql
    assert owner not in sql
    assert f"%{title}%" in compiled.params.values()
    assert content_type in compiled.params.values()
    assert owner in compiled.params.values()
