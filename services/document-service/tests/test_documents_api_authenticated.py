"""Tests for the JWT-authenticated document endpoints.

The read/write endpoints below call ``_require_user_id`` and therefore need an
``Authorization: Bearer`` header; the shared ``client`` fixture does not send one.
"""

import uuid

import jwt
import pytest
from httpx import AsyncClient

SECRET = "document-service-unit-test-secret-key"


@pytest.fixture
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("JWT_SECRET", SECRET)
    return SECRET


def _bearer(user_id: uuid.UUID, secret: str = SECRET, algorithm: str = "HS256") -> dict[str, str]:
    token = jwt.encode({"user_id": str(user_id)}, secret, algorithm=algorithm)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth(jwt_secret: str, owner_id: uuid.UUID) -> dict[str, str]:
    return _bearer(owner_id)


async def _create(client: AsyncClient, owner_id: uuid.UUID, **overrides) -> dict:
    payload = {"title": "Doc", "content": "Body", "owner_id": str(owner_id)}
    payload.update(overrides)
    resp = await client.post("/api/v1/documents/", json=payload)
    assert resp.status_code == 201
    return resp.json()


# ---- GET /{document_id} ----


async def test_get_document_returns_owned_document(client, owner_id, auth):
    doc = await _create(client, owner_id)

    resp = await client.get(f"/api/v1/documents/{doc['id']}", headers=auth)

    assert resp.status_code == 200
    assert resp.json()["id"] == doc["id"]


async def test_get_document_returns_404_for_unknown_id(client, auth):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=auth)

    assert resp.status_code == 404


async def test_get_document_returns_403_for_other_owner(client, owner_id, jwt_secret):
    doc = await _create(client, owner_id)

    resp = await client.get(
        f"/api/v1/documents/{doc['id']}", headers=_bearer(uuid.uuid4())
    )

    assert resp.status_code == 403


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("get", ""), ("delete", ""), ("get", "/versions"), ("get", "/export")],
)
async def test_read_endpoints_require_authentication(client, method, suffix):
    resp = await getattr(client, method)(f"/api/v1/documents/{uuid.uuid4()}{suffix}")

    assert resp.status_code == 401


@pytest.mark.parametrize("method", ["put", "patch"])
async def test_write_endpoints_require_authentication(client, method):
    resp = await getattr(client, method)(
        f"/api/v1/documents/{uuid.uuid4()}", json={"title": "Anonymous", "content": ""}
    )

    assert resp.status_code == 401


async def test_restore_version_requires_authentication(client):
    resp = await client.post(
        f"/api/v1/documents/{uuid.uuid4()}/versions/{uuid.uuid4()}/restore"
    )

    assert resp.status_code == 401


# ---- PUT / PATCH / DELETE ----


async def test_update_document_replaces_content_and_bumps_version(client, owner_id, auth):
    doc = await _create(client, owner_id, title="Original", content="Old body")

    resp = await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Updated", "content": "New body"},
        headers=auth,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert (data["title"], data["content"], data["version"]) == ("Updated", "New body", 2)


async def test_update_document_returns_404_for_unknown_id(client, auth):
    resp = await client.put(
        f"/api/v1/documents/{uuid.uuid4()}",
        json={"title": "Nope", "content": ""},
        headers=auth,
    )

    assert resp.status_code == 404


async def test_update_document_returns_403_for_other_owner(client, owner_id, jwt_secret):
    doc = await _create(client, owner_id)

    resp = await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Hijacked", "content": ""},
        headers=_bearer(uuid.uuid4()),
    )

    assert resp.status_code == 403


async def test_patch_document_only_changes_supplied_fields(client, owner_id, auth):
    doc = await _create(client, owner_id, title="Original", content="Body")

    resp = await client.patch(
        f"/api/v1/documents/{doc['id']}", json={"title": "Patched"}, headers=auth
    )

    assert resp.status_code == 200
    data = resp.json()
    assert (data["title"], data["content"], data["version"]) == ("Patched", "Body", 2)


async def test_patch_document_updates_content_type_and_folder(client, owner_id, auth):
    doc = await _create(client, owner_id)
    folder = uuid.uuid4()

    resp = await client.patch(
        f"/api/v1/documents/{doc['id']}",
        json={"content": "one two three", "content_type": "text/html", "folder_id": str(folder)},
        headers=auth,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["content_type"] == "text/html"
    assert data["folder_id"] == str(folder)
    assert data["word_count"] == 3


async def test_patch_document_with_empty_body_is_a_noop(client, owner_id, auth):
    doc = await _create(client, owner_id)

    resp = await client.patch(f"/api/v1/documents/{doc['id']}", json={}, headers=auth)

    assert resp.status_code == 200
    assert resp.json()["version"] == 1


async def test_patch_document_rejects_explicit_null_title(client, owner_id, auth):
    doc = await _create(client, owner_id)

    resp = await client.patch(
        f"/api/v1/documents/{doc['id']}", json={"title": None}, headers=auth
    )

    assert resp.status_code == 422


async def test_patch_document_returns_404_for_unknown_id(client, auth):
    resp = await client.patch(
        f"/api/v1/documents/{uuid.uuid4()}", json={"title": "x"}, headers=auth
    )

    assert resp.status_code == 404


async def test_delete_document_soft_deletes_it(client, owner_id, auth):
    doc = await _create(client, owner_id)

    assert (await client.delete(f"/api/v1/documents/{doc['id']}", headers=auth)).status_code == 204
    assert (await client.get(f"/api/v1/documents/{doc['id']}", headers=auth)).status_code == 404


async def test_delete_document_returns_404_for_unknown_id(client, auth):
    resp = await client.delete(f"/api/v1/documents/{uuid.uuid4()}", headers=auth)

    assert resp.status_code == 404


async def test_delete_document_returns_403_for_other_owner(client, owner_id, jwt_secret):
    doc = await _create(client, owner_id)

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}", headers=_bearer(uuid.uuid4())
    )

    assert resp.status_code == 403


# ---- Versions ----


async def test_list_versions_returns_versions_in_ascending_order(client, owner_id, auth):
    doc = await _create(client, owner_id, title="Versioned", content="v1")
    await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Versioned", "content": "v2"},
        headers=auth,
    )

    resp = await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=auth)

    assert resp.status_code == 200
    assert [v["version_number"] for v in resp.json()] == [1, 2]


async def test_list_versions_returns_404_for_unknown_document(client, auth):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}/versions", headers=auth)

    assert resp.status_code == 404


async def test_list_versions_returns_403_for_other_owner(client, owner_id, jwt_secret):
    doc = await _create(client, owner_id)

    resp = await client.get(
        f"/api/v1/documents/{doc['id']}/versions", headers=_bearer(uuid.uuid4())
    )

    assert resp.status_code == 403


async def test_restore_version_reinstates_earlier_content(client, owner_id, auth):
    doc = await _create(client, owner_id, title="Restore Me", content="Original")
    await client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Changed", "content": "Changed body"},
        headers=auth,
    )
    versions = (await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=auth)).json()
    first = next(v for v in versions if v["version_number"] == 1)

    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions/{first['id']}/restore", headers=auth
    )

    assert resp.status_code == 200
    data = resp.json()
    assert (data["title"], data["content"], data["version"]) == ("Restore Me", "Original", 3)


async def test_restore_version_returns_404_for_unknown_document(client, auth):
    resp = await client.post(
        f"/api/v1/documents/{uuid.uuid4()}/versions/{uuid.uuid4()}/restore", headers=auth
    )

    assert resp.status_code == 404


async def test_restore_version_returns_404_for_unknown_version(client, owner_id, auth):
    doc = await _create(client, owner_id)

    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions/{uuid.uuid4()}/restore", headers=auth
    )

    assert resp.status_code == 404


async def test_restore_version_returns_403_for_other_owner(client, owner_id, jwt_secret):
    doc = await _create(client, owner_id)

    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions/{uuid.uuid4()}/restore",
        headers=_bearer(uuid.uuid4()),
    )

    assert resp.status_code == 403


# ---- Export ----


@pytest.mark.parametrize(
    ("fmt", "content_type", "expected"),
    [
        ("html", "text/html", "<h1>Export</h1>"),
        ("markdown", "text/markdown", "# Export"),
        ("pdf", "application/pdf", "TITLE: Export"),
    ],
)
async def test_export_document_renders_each_format(
    client, owner_id, auth, fmt, content_type, expected
):
    doc = await _create(client, owner_id, title="Export", content="Content here")

    resp = await client.get(
        f"/api/v1/documents/{doc['id']}/export", params={"format": fmt}, headers=auth
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(content_type)
    assert expected in resp.text


async def test_export_document_rejects_unknown_format(client, owner_id, auth):
    doc = await _create(client, owner_id)

    resp = await client.get(
        f"/api/v1/documents/{doc['id']}/export", params={"format": "docx"}, headers=auth
    )

    assert resp.status_code == 422


async def test_export_document_returns_404_for_unknown_document(client, auth):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}/export", headers=auth)

    assert resp.status_code == 404


async def test_export_document_returns_403_for_other_owner(client, owner_id, jwt_secret):
    doc = await _create(client, owner_id)

    resp = await client.get(
        f"/api/v1/documents/{doc['id']}/export", headers=_bearer(uuid.uuid4())
    )

    assert resp.status_code == 403


# ---- Collection routes without the trailing slash ----


async def test_create_document_without_trailing_slash(client, owner_id):
    resp = await client.post(
        "/api/v1/documents",
        json={"title": "No Slash", "content": "x", "owner_id": str(owner_id)},
    )

    assert resp.status_code == 201
    assert resp.json()["title"] == "No Slash"


async def test_list_documents_without_trailing_slash(client, owner_id):
    await _create(client, owner_id)

    resp = await client.get("/api/v1/documents", params={"owner_id": str(owner_id)})

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_list_documents_falls_back_to_jwt_owner(client, owner_id, auth):
    await _create(client, owner_id)

    resp = await client.get("/api/v1/documents/", headers=auth)

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_list_documents_filters_by_folder(client, owner_id, folder_id):
    await _create(client, owner_id, folder_id=str(folder_id))
    await _create(client, owner_id, title="Other folder")

    resp = await client.get(
        "/api/v1/documents/",
        params={"owner_id": str(owner_id), "folder_id": str(folder_id)},
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_search_documents_paginates(client, owner_id):
    for i in range(3):
        await _create(client, owner_id, title=f"Report {i}")

    resp = await client.get(
        "/api/v1/documents/search", params={"q": "Report", "page": 2, "size": 2}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert (data["total"], data["pages"], len(data["items"])) == (3, 2, 1)


async def test_search_documents_escapes_wildcards(client, owner_id):
    await _create(client, owner_id, title="Plain title")

    resp = await client.get("/api/v1/documents/search", params={"q": "%"})

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---- Documents from templates ----


async def test_create_document_from_template(client, owner_id):
    template = await client.post(
        "/api/v1/templates/",
        json={
            "name": "Weekly Report",
            "description": "",
            "content": "## Agenda",
            "created_by": str(owner_id),
        },
    )
    template_id = template.json()["id"]

    resp = await client.post(
        f"/api/v1/documents/from-template/{template_id}",
        json={"title": "Week 12", "owner_id": str(owner_id)},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert (data["title"], data["content"]) == ("Week 12", "## Agenda")


async def test_create_document_from_unknown_template_returns_404(client, owner_id):
    resp = await client.post(
        f"/api/v1/documents/from-template/{uuid.uuid4()}",
        json={"title": "Week 12", "owner_id": str(owner_id)},
    )

    assert resp.status_code == 404
