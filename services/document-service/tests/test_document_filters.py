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
async def test_title_quote_is_bound_not_executed(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Quarterly Report")

    resp = await client.get(
        "/api/v1/documents/",
        params={"title": "x') AND 1=CAST((SELECT 'leak') AS int)--"},
        auth=None,
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_title_matches_quote_literally(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Owner's Report")
    await _create(client, owner_id, "Other Report")

    resp = await client.get("/api/v1/documents/", params={"title": "owner's"}, auth=None)

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Owner's Report"]


@pytest.mark.asyncio
async def test_title_like_wildcards_are_literal(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "100% Done")
    await _create(client, owner_id, "Plain")

    wildcard = await client.get("/api/v1/documents/", params={"title": "%"}, auth=None)
    underscore = await client.get("/api/v1/documents/", params={"title": "_"}, auth=None)

    assert [item["title"] for item in wildcard.json()["items"]] == ["100% Done"]
    assert underscore.json()["total"] == 0


@pytest.mark.asyncio
async def test_content_type_tautology_does_not_cross_owners(
    client: AsyncClient, owner_id: uuid.UUID
):
    other_owner = uuid.uuid4()
    await _create(client, owner_id, "Mine", content_type="text/markdown")
    await _create(client, other_owner, "Theirs", content_type="text/markdown")

    resp = await client.get(
        "/api/v1/documents/",
        params={"content_type": "text/markdown' OR '1'='1"},
        auth=None,
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"sort": "title; DROP TABLE documents"},
        {"sort": "(SELECT password_hash FROM users)"},
        {"sort": "content"},
        {"direction": "desc, (SELECT 1)"},
    ],
)
async def test_sort_outside_allow_list_is_rejected(client: AsyncClient, params: dict):
    resp = await client.get("/api/v1/documents/", params=params, auth=None)

    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid sort"}


@pytest.mark.asyncio
async def test_sort_is_case_insensitive(client: AsyncClient, owner_id: uuid.UUID):
    await _create(client, owner_id, "Beta")
    await _create(client, owner_id, "Alpha")

    resp = await client.get(
        "/api/v1/documents/", params={"sort": "Title", "direction": "ASC"}, auth=None
    )

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Alpha", "Beta"]


@pytest.mark.asyncio
async def test_repository_rejects_unlisted_sort(db_session):
    from app.services.document_query_repository import (
        DocumentQueryRepository,
        InvalidSortError,
    )

    repo = DocumentQueryRepository(db_session)
    with pytest.raises(InvalidSortError):
        await repo.search_documents(sort="title; DROP TABLE documents")
    with pytest.raises(InvalidSortError):
        await repo.search_documents(direction="desc; --")


@pytest.mark.asyncio
async def test_database_error_text_is_not_echoed(client: AsyncClient, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.services import document_query_repository as module

    async def boom(self, **_kwargs):
        raise OperationalError("SELECT secret FROM users", {}, Exception("syntax error"))

    monkeypatch.setattr(module.DocumentQueryRepository, "count_documents", boom)

    resp = await client.get("/api/v1/documents/", params={"title": "x"}, auth=None)

    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid filter"}


@pytest.mark.asyncio
async def test_owner_and_folder_filters_bind_as_uuid(
    client: AsyncClient, owner_id: uuid.UUID, folder_id: uuid.UUID
):
    await _create(client, owner_id, "In folder report", folder_id=str(folder_id))
    await _create(client, owner_id, "Loose report")
    await _create(client, uuid.uuid4(), "Someone else's report", folder_id=str(folder_id))

    resp = await client.get(
        "/api/v1/documents/",
        params={"owner_id": str(owner_id), "folder_id": str(folder_id), "title": "report"},
        auth=None,
    )

    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["In folder report"]


def test_uuid_filters_render_as_typed_binds_on_postgres():
    from sqlalchemy.dialects.postgresql import asyncpg

    from app.services.document_query_repository import DocumentQueryRepository, _statement

    where, params = DocumentQueryRepository(None)._where(
        str(uuid.uuid4()), "x", "text/html", str(uuid.uuid4())
    )
    compiled = str(
        _statement(f"SELECT 1 FROM documents WHERE {where}", params).compile(
            dialect=asyncpg.dialect()
        )
    )

    assert compiled.count("::UUID") == 2
    assert "::VARCHAR" in compiled
