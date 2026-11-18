"""Auth, ownership, not-found and JWT edge cases for the document routes."""

import uuid

import jwt
import pytest
from httpx import AsyncClient

from app.services.document_query_repository import DocumentQueryRepository
from tests.conftest import TEST_JWT_SECRET, bearer_auth

BASE = "/api/v1/documents"


async def _create(client: AsyncClient, owner_id: uuid.UUID, **kwargs) -> dict:
    payload = {"title": "Doc", "content": "Body", "owner_id": str(owner_id)}
    payload.update(kwargs)
    resp = await client.post(f"{BASE}/", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _token(claims: dict, secret: str = TEST_JWT_SECRET) -> str:
    return jwt.encode(claims, secret, algorithm="HS256")


def _per_document_requests(doc_id: str, version_id: str) -> list[tuple[str, str, dict]]:
    return [
        ("GET", f"{BASE}/{doc_id}", {}),
        ("PUT", f"{BASE}/{doc_id}", {"json": {"title": "New"}}),
        ("PATCH", f"{BASE}/{doc_id}", {"json": {"title": "New"}}),
        ("DELETE", f"{BASE}/{doc_id}", {}),
        ("GET", f"{BASE}/{doc_id}/versions", {}),
        ("POST", f"{BASE}/{doc_id}/versions/{version_id}/restore", {}),
        ("POST", f"{BASE}/{doc_id}/share", {}),
        ("GET", f"{BASE}/{doc_id}/export", {}),
    ]


@pytest.mark.asyncio
async def test_per_document_routes_require_authentication(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id)
    for method, url, kwargs in _per_document_requests(doc["id"], str(uuid.uuid4())):
        resp = await client.request(method, url, auth=None, **kwargs)
        assert resp.status_code == 401, (method, url)
        assert resp.json()["detail"] == "Authentication required"


@pytest.mark.asyncio
async def test_per_document_routes_reject_other_users(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id)
    intruder = bearer_auth(uuid.uuid4())
    for method, url, kwargs in _per_document_requests(doc["id"], str(uuid.uuid4())):
        resp = await client.request(method, url, auth=intruder, **kwargs)
        assert resp.status_code == 403, (method, url)
        assert resp.json()["detail"] == "Access denied"

    resp = await client.get(f"{BASE}/{doc['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Doc"
    assert resp.json()["version"] == 1


@pytest.mark.asyncio
async def test_per_document_routes_404_for_missing_document(client: AsyncClient):
    for method, url, kwargs in _per_document_requests(
        str(uuid.uuid4()), str(uuid.uuid4())
    ):
        resp = await client.request(method, url, **kwargs)
        assert resp.status_code == 404, (method, url)


@pytest.mark.asyncio
async def test_per_document_routes_404_after_soft_delete(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id)
    assert (await client.delete(f"{BASE}/{doc['id']}")).status_code == 204
    for method, url, kwargs in _per_document_requests(doc["id"], str(uuid.uuid4())):
        resp = await client.request(method, url, **kwargs)
        assert resp.status_code == 404, (method, url)


@pytest.mark.asyncio
async def test_restore_unknown_version_returns_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id)
    resp = await client.post(f"{BASE}/{doc['id']}/versions/{uuid.uuid4()}/restore")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Document or version not found"


@pytest.mark.asyncio
async def test_restore_version_of_another_document_returns_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_a = await _create(client, owner_id, title="A")
    doc_b = await _create(client, owner_id, title="B")
    versions_b = (await client.get(f"{BASE}/{doc_b['id']}/versions")).json()

    resp = await client.post(
        f"{BASE}/{doc_a['id']}/versions/{versions_b[0]['id']}/restore"
    )
    assert resp.status_code == 404
    assert (await client.get(f"{BASE}/{doc_a['id']}")).json()["title"] == "A"


@pytest.mark.asyncio
async def test_export_pdf_route(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id, title="Report", content="Numbers")
    resp = await client.get(f"{BASE}/{doc['id']}/export", params={"format": "pdf"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")


@pytest.mark.asyncio
async def test_export_rejects_unknown_format(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id)
    resp = await client.get(f"{BASE}/{doc['id']}/export", params={"format": "docx"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_shared_link_for_deleted_document_returns_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id)
    token = (await client.post(f"{BASE}/{doc['id']}/share")).json()["token"]
    assert (await client.delete(f"{BASE}/{doc['id']}")).status_code == 204

    resp = await client.get(
        f"{BASE}/shared", params={"document_id": doc["id"], "token": token}, auth=None
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_shared_link_with_bad_token_returns_403(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id)
    resp = await client.get(
        f"{BASE}/shared", params={"document_id": doc["id"], "token": "nope"}, auth=None
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_and_list_without_trailing_slash(
    client: AsyncClient, owner_id: uuid.UUID
):
    resp = await client.post(BASE, json={"title": "No slash", "content": "x"})
    assert resp.status_code == 201
    assert resp.json()["owner_id"] == str(owner_id)

    listed = await client.get(BASE)
    assert listed.status_code == 200
    assert [d["title"] for d in listed.json()["items"]] == ["No slash"]

    filtered = await client.get(BASE, params={"title": "slash"}, auth=None)
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_scopes_to_authenticated_owner(
    client: AsyncClient, owner_id: uuid.UUID
):
    await _create(client, owner_id, title="Mine")
    await _create(client, uuid.uuid4(), title="Theirs")

    resp = await client.get(f"{BASE}/")
    assert [d["title"] for d in resp.json()["items"]] == ["Mine"]


@pytest.mark.asyncio
async def test_filter_scoped_by_owner_and_folder_is_served(
    client: AsyncClient, owner_id: uuid.UUID, folder_id: uuid.UUID
):
    await _create(client, owner_id, title="Plan", folder_id=str(folder_id))
    resp = await client.get(
        f"{BASE}/", params={"title": "plan", "folder_id": str(folder_id)}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_filter_repository_scopes_by_owner_and_folder(
    client: AsyncClient, db_session, owner_id: uuid.UUID, folder_id: uuid.UUID
):
    await _create(client, owner_id, title="Plan in folder", folder_id=str(folder_id))
    await _create(client, owner_id, title="Plan loose")
    await _create(client, uuid.uuid4(), title="Plan other", folder_id=str(folder_id))

    # SQLite stores UUID columns as 32-char hex, so scope with .hex here.
    repo = DocumentQueryRepository(db_session)
    scoped = {"owner_id": owner_id.hex, "folder_id": folder_id.hex}
    assert await repo.count_documents(**scoped) == 1
    rows = await repo.search_documents(**scoped, title_contains="plan")
    assert [r["title"] for r in rows] == ["Plan in folder"]
    assert await repo.count_documents(owner_id=owner_id.hex) == 2
    assert await repo.count_documents(folder_id=folder_id.hex) == 2


@pytest.mark.asyncio
async def test_filter_with_unknown_sort_column_returns_400(
    client: AsyncClient, owner_id: uuid.UUID
):
    await _create(client, owner_id)
    resp = await client.get(f"{BASE}/", params={"sort": "no_such_column"})
    assert resp.status_code == 400
    assert resp.json()["detail"].startswith("Invalid filter")


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="OW-SEC-401: filter values are interpolated into SQL, so a quote breaks the query",
)
async def test_filter_title_with_apostrophe_matches(
    client: AsyncClient, owner_id: uuid.UUID
):
    await _create(client, owner_id, title="O'Brien notes")
    resp = await client.get(f"{BASE}/", params={"title": "o'brien"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_invalid_jwt_is_unauthenticated(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id)
    bad = _token({"user_id": str(owner_id)}, secret="wrong-secret-wrong-secret-wrong-32")
    for header in (f"Bearer {bad}", "Bearer not-a-jwt", f"Token {bad}"):
        resp = await client.get(f"{BASE}/{doc['id']}", headers={"Authorization": header})
        assert resp.status_code == 401, header


@pytest.mark.asyncio
async def test_jwt_without_user_claim_is_unauthenticated(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id)
    token = _token({"role": "user"})
    resp = await client.get(
        f"{BASE}/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_jwt_with_non_uuid_user_claim_is_unauthenticated(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create(client, owner_id)
    token = _token({"user_id": "not-a-uuid"})
    resp = await client.get(
        f"{BASE}/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_jwt_sub_claim_is_accepted(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create(client, owner_id)
    token = _token({"sub": str(owner_id)})
    resp = await client.get(
        f"{BASE}/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_x_user_id_fallback_when_no_jwt_secret(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch
):
    doc = await _create(client, owner_id)
    monkeypatch.setenv("JWT_SECRET", "")
    headers = {"Authorization": "Bearer unsigned"}

    ok = await client.get(
        f"{BASE}/{doc['id']}", headers={**headers, "X-User-ID": str(owner_id)}
    )
    assert ok.status_code == 200

    bad = await client.get(
        f"{BASE}/{doc['id']}", headers={**headers, "X-User-ID": "not-a-uuid"}
    )
    assert bad.status_code == 401

    missing = await client.get(f"{BASE}/{doc['id']}", headers=headers)
    assert missing.status_code == 401
