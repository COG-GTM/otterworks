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
async def test_title_with_quote_matches_its_own_document(
    client: AsyncClient, owner_id: uuid.UUID
):
    await _create(client, owner_id, "Owner's Manual")
    await _create(client, owner_id, "Owners Manual")

    resp = await client.get("/api/v1/documents/", params={"title": "owner's"}, auth=None)

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Owner's Manual"]


@pytest.mark.asyncio
async def test_title_like_wildcards_are_literal(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "100% Plan")
    await _create(client, owner_id, "Plan_B")
    await _create(client, owner_id, "Other Plan")

    percent = await client.get("/api/v1/documents/", params={"title": "%"}, auth=None)
    underscore = await client.get("/api/v1/documents/", params={"title": "_"}, auth=None)

    assert [item["title"] for item in percent.json()["items"]] == ["100% Plan"]
    assert [item["title"] for item in underscore.json()["items"]] == ["Plan_B"]


@pytest.mark.asyncio
async def test_content_type_tautology_does_not_cross_owners(
    client: AsyncClient, owner_id: uuid.UUID
):
    other_owner = uuid.uuid4()
    await _create(client, owner_id, "Mine", content_type="text/markdown")
    await _create(client, other_owner, "Theirs", content_type="text/markdown")

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
        {"sort": "content"},
        {"sort": "title", "direction": "desc; DROP TABLE documents"},
        {"sort": "title", "direction": "sideways"},
    ],
)
async def test_sort_outside_allow_list_is_rejected(
    client: AsyncClient, owner_id: uuid.UUID, params: dict
):
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get("/api/v1/documents/", params=params, auth=None)

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail.startswith("Invalid sort:")
    assert "DROP" not in detail and "SELECT" not in detail

    still_there = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id)}, auth=None
    )
    assert still_there.json()["total"] == 1


@pytest.mark.asyncio
async def test_sort_direction_is_case_insensitive(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Beta plan")
    await _create(client, owner_id, "Alpha plan")

    resp = await client.get(
        "/api/v1/documents/", params={"sort": "title", "direction": "ASC"}, auth=None
    )

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Alpha plan", "Beta plan"]


@pytest.mark.asyncio
async def test_database_error_text_is_not_returned(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from sqlalchemy.exc import OperationalError

    from app.services.document_query_repository import DocumentQueryRepository

    async def _boom(self, **kwargs):
        raise OperationalError("SELECT secret FROM users", {}, Exception("password_hash"))

    monkeypatch.setattr(DocumentQueryRepository, "count_documents", _boom)

    resp = await client.get("/api/v1/documents/", params={"title": "x"}, auth=None)

    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid filter"}


def test_filter_values_are_bound_not_interpolated():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.services.document_query_repository import (
        DocumentQueryRepository,
        _documents,
        resolve_order_by,
    )

    payload = "x') OR 1=1--"
    stmt = (
        select(*_documents.c)
        .where(*DocumentQueryRepository(None)._where(None, payload, payload, None))
        .order_by(resolve_order_by("title", "asc"))
    )
    compiled = stmt.compile(dialect=postgresql.asyncpg.dialect())

    assert payload not in str(compiled)
    assert compiled.params["content_type"] == payload
    assert compiled.params["title_pattern"] == "%x') OR 1=1--%"
