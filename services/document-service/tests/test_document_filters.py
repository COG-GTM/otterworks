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
    await _create(client, owner_id, "Owner's Report")
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get("/api/v1/documents/", params={"title": "owner's"}, auth=None)

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Owner's Report"]


@pytest.mark.asyncio
async def test_title_like_wildcards_are_matched_literally(
    client: AsyncClient, owner_id: uuid.UUID
):
    await _create(client, owner_id, "100% done")
    await _create(client, owner_id, "1000 done")
    await _create(client, owner_id, "snake_case")
    await _create(client, owner_id, "snakeXcase")

    percent = await client.get("/api/v1/documents/", params={"title": "100%"}, auth=None)
    underscore = await client.get("/api/v1/documents/", params={"title": "e_c"}, auth=None)

    assert [item["title"] for item in percent.json()["items"]] == ["100% done"]
    assert [item["title"] for item in underscore.json()["items"]] == ["snake_case"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"title": "x%' OR 1=1 --"},
        {"title": "x') UNION SELECT 1,2,3,4,5,6,7,8,9,10,11,12 --"},
        {"content_type": "text/markdown' OR '1'='1"},
    ],
)
async def test_filter_values_cannot_escape_owner_scope(
    client: AsyncClient, owner_id: uuid.UUID, params: dict[str, str]
):
    await _create(client, uuid.uuid4(), "Someone else's notes")

    resp = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id), **params}, auth=None
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"sort": "id;--"},
        {"sort": "title; DROP TABLE documents"},
        {"sort": "(SELECT password_hash FROM users LIMIT 1)"},
        {"sort": "title", "direction": "desc; SELECT 1"},
        {"sort": "title", "direction": "sideways"},
    ],
)
async def test_unlisted_sort_is_rejected_without_database_text(
    client: AsyncClient, owner_id: uuid.UUID, params: dict[str, str]
):
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get("/api/v1/documents/", params=params, auth=None)

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "Unsupported sort" in detail
    for leaked in ("SELECT", "FROM documents", "sqlite", "syntax", "DROP"):
        assert leaked not in detail


@pytest.mark.asyncio
async def test_direction_is_case_insensitive(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Beta plan")
    await _create(client, owner_id, "Alpha plan")

    resp = await client.get(
        "/api/v1/documents/", params={"sort": "title", "direction": "ASC"}, auth=None
    )

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Alpha plan", "Beta plan"]


@pytest.mark.asyncio
async def test_database_error_is_not_echoed(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
):
    from sqlalchemy.exc import OperationalError

    from app.services.document_query_repository import DocumentQueryRepository

    async def _boom(self, **_kwargs):
        raise OperationalError("SELECT secret FROM users", {}, Exception("syntax error"))

    monkeypatch.setattr(DocumentQueryRepository, "count_documents", _boom)

    resp = await client.get("/api/v1/documents/", params={"title": "x"}, auth=None)

    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid filter"}


def test_compiled_statement_binds_caller_values():
    from sqlalchemy.dialects import postgresql

    from app.services.document_query_repository import DocumentQueryRepository

    title = "x%' OR 1=1 --"
    content_type = "text/html' OR '1'='1"
    owner = "aaaaaaaa-0000-4000-8000-00000000000a"
    repo = DocumentQueryRepository(db=None)
    stmt = repo._search_statement(owner, title, content_type, None, "title", "asc", 20, 0)
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "OR 1=1" not in sql
    assert "OR '1'='1" not in sql
    assert owner not in sql
    assert "%(title_pattern)s" in sql
    assert "%(content_type)s" in sql
    assert "%(owner_id)s" in sql
    assert "ORDER BY documents.title ASC" in sql
    assert compiled.params["title_pattern"] == "%x!%' OR 1=1 --%"
    assert compiled.params["content_type"] == content_type
    assert compiled.params["owner_id"] == uuid.UUID(owner)
