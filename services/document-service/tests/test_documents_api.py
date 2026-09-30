"""Tests for document API endpoints."""

import os
import uuid

import jwt
import pytest
from httpx import AsyncClient

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105
os.environ.setdefault("JWT_SECRET", TEST_JWT_SECRET)


def _make_jwt(user_id: str) -> str:
    return jwt.encode({"user_id": user_id}, TEST_JWT_SECRET, algorithm="HS256")


@pytest.mark.asyncio
async def test_create_document(client: AsyncClient, owner_id: uuid.UUID):
    resp = await client.post(
        "/api/v1/documents/",
        json={
            "title": "Test Document",
            "content": "Hello world",
            "owner_id": str(owner_id),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test Document"
    assert data["content"] == "Hello world"
    assert data["word_count"] == 2
    assert data["version"] == 1
    assert data["owner_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_get_document(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "Body", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_get_document_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_documents(client: AsyncClient, owner_id: uuid.UUID):
    for i in range(3):
        await client.post(
            "/api/v1/documents/",
            json={"title": f"Doc {i}", "content": "", "owner_id": str(owner_id)},
        )
    resp = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


@pytest.mark.asyncio
async def test_list_documents_pagination(client: AsyncClient, owner_id: uuid.UUID):
    for i in range(5):
        await client.post(
            "/api/v1/documents/",
            json={"title": f"Doc {i}", "content": "", "owner_id": str(owner_id)},
        )
    resp = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id), "page": 1, "size": 2}
    )
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["pages"] == 3


@pytest.mark.asyncio
async def test_update_document(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Original", "content": "Old body", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Updated", "content": "New body"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated"
    assert data["content"] == "New body"
    assert data["version"] == 2


@pytest.mark.asyncio
async def test_patch_document(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Original", "content": "Body", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Patched Title"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Patched Title"
    assert data["content"] == "Body"  # unchanged
    assert data["version"] == 2


@pytest.mark.asyncio
async def test_delete_document(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "To Delete", "content": "", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_document_versions(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Versioned", "content": "v1", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    await client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Versioned", "content": "v2"},
    )

    resp = await client.get(f"/api/v1/documents/{doc_id}/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 2
    assert versions[0]["version_number"] == 2
    assert versions[1]["version_number"] == 1


@pytest.mark.asyncio
async def test_restore_version(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Restore Me", "content": "Original", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    await client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Changed", "content": "Changed body"},
    )

    versions_resp = await client.get(f"/api/v1/documents/{doc_id}/versions")
    v1_id = versions_resp.json()[-1]["id"]  # first version

    resp = await client.post(f"/api/v1/documents/{doc_id}/versions/{v1_id}/restore")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Restore Me"
    assert data["content"] == "Original"
    assert data["version"] == 3


@pytest.mark.asyncio
async def test_search_documents(client: AsyncClient, owner_id: uuid.UUID):
    await client.post(
        "/api/v1/documents/",
        json={"title": "Python Guide", "content": "Learn Python", "owner_id": str(owner_id)},
    )
    await client.post(
        "/api/v1/documents/",
        json={"title": "Rust Guide", "content": "Learn Rust", "owner_id": str(owner_id)},
    )

    resp = await client.get("/api/v1/documents/search", params={"q": "Python"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Python Guide"


@pytest.mark.asyncio
async def test_export_document_html(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Export", "content": "Content here", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/documents/{doc_id}/export", params={"format": "html"}
    )
    assert resp.status_code == 200
    assert "<h1>Export</h1>" in resp.text


@pytest.mark.asyncio
async def test_export_document_markdown(client: AsyncClient, owner_id: uuid.UUID):
    create_resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Export MD", "content": "MD content", "owner_id": str(owner_id)},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/documents/{doc_id}/export", params={"format": "markdown"}
    )
    assert resp.status_code == 200
    assert "# Export MD" in resp.text


@pytest.mark.asyncio
async def test_create_document_via_jwt(client: AsyncClient):
    """Create a document without owner_id in the body, using JWT instead."""
    user_id = uuid.uuid4()
    token = _make_jwt(str(user_id))
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "JWT Doc", "content": "Created via JWT"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "JWT Doc"
    assert data["owner_id"] == str(user_id)


@pytest.mark.asyncio
async def test_create_document_via_jwt_hs384(client: AsyncClient):
    """Create a document using an HS384-signed JWT (matches auth-service algorithm)."""
    user_id = uuid.uuid4()
    token = jwt.encode({"sub": str(user_id)}, TEST_JWT_SECRET, algorithm="HS384")
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "HS384 Doc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["owner_id"] == str(user_id)


@pytest.mark.asyncio
async def test_create_document_x_user_id_header_ignored(client: AsyncClient):
    """X-User-Id header alone is not trusted (prevents identity spoofing)."""
    user_id = uuid.uuid4()
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Header Doc"},
        headers={"X-User-Id": str(user_id)},
        auth=None,  # opt out of the client fixture's default bearer token
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_document_no_auth_returns_401(client: AsyncClient):
    """Creating a document without owner_id and without auth returns 401."""
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "No Auth Doc"},
        auth=None,  # opt out of the client fixture's default bearer token
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trash_lists_only_callers_deleted_documents(
    client: AsyncClient, owner_id: uuid.UUID
):
    live = await client.post("/api/v1/documents/", json={"title": "Live", "content": ""})
    first = await client.post("/api/v1/documents/", json={"title": "First", "content": ""})
    second = await client.post("/api/v1/documents/", json={"title": "Second", "content": ""})
    first_id, second_id = first.json()["id"], second.json()["id"]

    other_id = uuid.uuid4()
    other_headers = {"Authorization": f"Bearer {_make_jwt(str(other_id))}"}
    other_doc = await client.post(
        "/api/v1/documents/",
        json={"title": "Other", "content": ""},
        headers=other_headers,
    )
    await client.delete(f"/api/v1/documents/{other_doc.json()['id']}", headers=other_headers)

    assert (await client.delete(f"/api/v1/documents/{first_id}")).status_code == 204
    assert (await client.delete(f"/api/v1/documents/{second_id}")).status_code == 204

    resp = await client.get("/api/v1/documents/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert [item["id"] for item in data["items"]] == [second_id, first_id]
    assert all(item["is_deleted"] and item["deleted_at"] for item in data["items"])
    assert live.json()["id"] not in {item["id"] for item in data["items"]}

    paged = await client.get("/api/v1/documents/trash", params={"page": 2, "size": 1})
    assert paged.status_code == 200
    assert paged.json()["pages"] == 2
    assert [item["id"] for item in paged.json()["items"]] == [first_id]

    listed = await client.get("/api/v1/documents/")
    assert {item["id"] for item in listed.json()["items"]} == {live.json()["id"]}


@pytest.mark.asyncio
async def test_trash_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/documents/trash", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_restore_document_keeps_content_and_versions(
    client: AsyncClient, owner_id: uuid.UUID
):
    create_resp = await client.post(
        "/api/v1/documents/", json={"title": "Restorable", "content": "v1 body"}
    )
    doc_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/documents/{doc_id}", json={"content": "v2 body"})

    assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404

    resp = await client.post(f"/api/v1/documents/{doc_id}/restore")
    assert resp.status_code == 200
    restored = resp.json()
    assert restored["id"] == doc_id
    assert restored["is_deleted"] is False
    assert restored["deleted_at"] is None
    assert restored["content"] == "v2 body"
    assert restored["version"] == 2

    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 200
    versions = await client.get(f"/api/v1/documents/{doc_id}/versions")
    assert [v["version_number"] for v in versions.json()] == [2, 1]

    trash = await client.get("/api/v1/documents/trash")
    assert trash.json()["total"] == 0


@pytest.mark.asyncio
async def test_restore_not_in_trash_returns_404(client: AsyncClient):
    create_resp = await client.post("/api/v1/documents/", json={"title": "Live", "content": ""})
    doc_id = create_resp.json()["id"]

    assert (await client.post(f"/api/v1/documents/{doc_id}/restore")).status_code == 404
    assert (await client.post(f"/api/v1/documents/{uuid.uuid4()}/restore")).status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_purges_trashed_document(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/documents/", json={"title": "Purge Me", "content": "bye"}
    )
    doc_id = create_resp.json()["id"]
    await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "a comment"},
    )

    # Default DELETE is still a soft delete.
    assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204
    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 1

    resp = await client.delete(f"/api/v1/documents/{doc_id}", params={"permanent": "true"})
    assert resp.status_code == 204

    assert (await client.get("/api/v1/documents/trash")).json()["total"] == 0
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 404
    assert (await client.post(f"/api/v1/documents/{doc_id}/restore")).status_code == 404
    assert (
        await client.delete(f"/api/v1/documents/{doc_id}", params={"permanent": "true"})
    ).status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_requires_document_in_trash(client: AsyncClient):
    create_resp = await client.post("/api/v1/documents/", json={"title": "Live", "content": ""})
    doc_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/documents/{doc_id}", params={"permanent": "true"})
    assert resp.status_code == 404
    assert (await client.get(f"/api/v1/documents/{doc_id}")).status_code == 200


@pytest.mark.asyncio
async def test_trash_actions_denied_for_other_owner(client: AsyncClient):
    create_resp = await client.post("/api/v1/documents/", json={"title": "Mine", "content": ""})
    doc_id = create_resp.json()["id"]
    assert (await client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204

    other_headers = {"Authorization": f"Bearer {_make_jwt(str(uuid.uuid4()))}"}

    trash = await client.get("/api/v1/documents/trash", headers=other_headers)
    assert trash.status_code == 200
    assert trash.json()["total"] == 0

    resp = await client.post(f"/api/v1/documents/{doc_id}/restore", headers=other_headers)
    assert resp.status_code == 403

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}", params={"permanent": "true"}, headers=other_headers
    )
    assert resp.status_code == 403

    # Still restorable by the owner afterwards.
    assert (await client.post(f"/api/v1/documents/{doc_id}/restore")).status_code == 200
