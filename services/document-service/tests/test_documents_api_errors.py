"""Ownership, not-found and alias-route behaviour of the documents API."""

import uuid

import jwt
import pytest
from httpx import AsyncClient

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    token = jwt.encode({"user_id": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _create_document(client: AsyncClient, owner_id: uuid.UUID, **overrides) -> dict:
    payload = {"title": "Doc", "content": "hello world", "owner_id": str(owner_id)}
    payload.update(overrides)
    resp = await client.post("/api/v1/documents/", json=payload)
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_create_document_without_trailing_slash(client: AsyncClient, owner_id: uuid.UUID):
    resp = await client.post(
        "/api/v1/documents",
        json={"title": "No slash", "content": "one two three", "owner_id": str(owner_id)},
    )

    assert resp.status_code == 201
    assert resp.json()["title"] == "No slash"
    assert resp.json()["word_count"] == 3


@pytest.mark.asyncio
async def test_create_document_no_slash_requires_identity(client: AsyncClient):
    resp = await client.post(
        "/api/v1/documents",
        json={"title": "No slash", "content": "body"},
        auth=None,
    )

    assert resp.status_code == 401
    assert "owner_id is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_documents_without_trailing_slash(client: AsyncClient, owner_id: uuid.UUID):
    await _create_document(client, owner_id, title="Listed")

    resp = await client.get("/api/v1/documents")

    assert resp.status_code == 200
    body = resp.json()
    assert [item["title"] for item in body["items"]] == ["Listed"]
    assert body["total"] == 1
    assert body["pages"] == 1


@pytest.mark.asyncio
async def test_list_documents_no_slash_scopes_to_explicit_owner(
    client: AsyncClient, owner_id: uuid.UUID
):
    await _create_document(client, owner_id, title="Mine")

    resp = await client.get("/api/v1/documents", params={"owner_id": str(uuid.uuid4())})

    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_search_documents_paginates(client: AsyncClient, owner_id: uuid.UUID):
    for i in range(3):
        await _create_document(client, owner_id, title=f"Quarterly report {i}")
    await _create_document(client, owner_id, title="Unrelated", content="nothing here")

    resp = await client.get(
        "/api/v1/documents/search", params={"q": "Quarterly", "page": 1, "size": 2}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_document_of_another_owner_is_forbidden(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)

    resp = await client.get(f"/api/v1/documents/{doc['id']}", headers=_auth_header(uuid.uuid4()))

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Access denied"


@pytest.mark.asyncio
async def test_get_document_requires_authentication(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create_document(client, owner_id)

    resp = await client.get(f"/api/v1/documents/{doc['id']}", auth=None)

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_document_not_found(client: AsyncClient):
    resp = await client.put(
        f"/api/v1/documents/{uuid.uuid4()}",
        json={"title": "T", "content": "c", "content_type": "text/plain"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_update_document_of_another_owner_is_forbidden(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)

    resp = await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Hijacked", "content": "c", "content_type": "text/plain"},
        headers=_auth_header(uuid.uuid4()),
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_document_not_found(client: AsyncClient):
    resp = await client.patch(f"/api/v1/documents/{uuid.uuid4()}", json={"title": "T"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_document_of_another_owner_is_forbidden(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)

    resp = await client.patch(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Hijacked"},
        headers=_auth_header(uuid.uuid4()),
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_document_not_found(client: AsyncClient):
    resp = await client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_of_another_owner_is_forbidden(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}", headers=_auth_header(uuid.uuid4())
    )

    assert resp.status_code == 403
    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_list_versions_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}/versions")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_versions_of_another_owner_is_forbidden(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)

    resp = await client.get(
        f"/api/v1/documents/{doc['id']}/versions", headers=_auth_header(uuid.uuid4())
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_restore_version_document_not_found(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/documents/{uuid.uuid4()}/versions/{uuid.uuid4()}/restore"
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Document or version not found"


@pytest.mark.asyncio
async def test_restore_unknown_version_returns_404(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create_document(client, owner_id)

    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions/{uuid.uuid4()}/restore"
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Document or version not found"


@pytest.mark.asyncio
async def test_restore_version_of_another_owner_is_forbidden(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)
    versions = (await client.get(f"/api/v1/documents/{doc['id']}/versions")).json()

    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions/{versions[0]['id']}/restore",
        headers=_auth_header(uuid.uuid4()),
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_export_document_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}/export")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_document_of_another_owner_is_forbidden(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc = await _create_document(client, owner_id)

    resp = await client.get(
        f"/api/v1/documents/{doc['id']}/export", headers=_auth_header(uuid.uuid4())
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_export_document_pdf_format(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create_document(client, owner_id, title="Report", content="body text")

    resp = await client.get(f"/api/v1/documents/{doc['id']}/export", params={"format": "pdf"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.text == "TITLE: Report\n\nbody text"


@pytest.mark.asyncio
async def test_export_document_rejects_unknown_format(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create_document(client, owner_id)

    resp = await client.get(f"/api/v1/documents/{doc['id']}/export", params={"format": "docx"})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_export_document_requires_authentication(client: AsyncClient, owner_id: uuid.UUID):
    doc = await _create_document(client, owner_id)

    resp = await client.get(f"/api/v1/documents/{doc['id']}/export", auth=None)

    assert resp.status_code == 401
