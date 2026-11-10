"""Tests for document API endpoints."""

import os
import uuid

import httpx
import jwt
import pytest
from httpx import AsyncClient

from tests.conftest import CLIENT_IP, GATEWAY_HEADERS, REQUEST_ID

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


async def _create_doc(client: AsyncClient, owner_id: uuid.UUID, content: str = "Body") -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Audited", "content": content, "owner_id": str(owner_id)},
    )
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_export_is_audited_with_format(client, owner_id, audit_sink):
    doc_id = await _create_doc(client, owner_id, content="confidential export body")
    resp = await client.get(
        f"/api/v1/documents/{doc_id}/export", params={"format": "html"}, headers=GATEWAY_HEADERS
    )
    assert resp.status_code == 200

    event = await audit_sink.only("export")
    audit_sink.assert_request(
        event, user_id=str(owner_id), outcome="success", ip=CLIENT_IP, request_id=REQUEST_ID
    )
    assert (event["resourceType"], event["resourceId"]) == ("document", doc_id)
    assert event["details"] == {"format": "html"}
    assert "confidential export body" not in audit_sink.requests[0].content.decode()


@pytest.mark.asyncio
async def test_non_owner_export_is_audited_as_permission_denied(client, owner_id, audit_sink):
    doc_id = await _create_doc(client, owner_id)
    intruder = uuid.uuid4()
    resp = await client.get(
        f"/api/v1/documents/{doc_id}/export",
        headers={**GATEWAY_HEADERS, "Authorization": f"Bearer {_make_jwt(str(intruder))}"},
    )
    assert resp.status_code == 403

    events = await audit_sink.events()
    assert [e["action"] for e in events] == ["permission.denied"]
    event = events[0]
    audit_sink.assert_request(
        event, user_id=str(intruder), outcome="denied", ip=CLIENT_IP, request_id=REQUEST_ID
    )
    assert (event["resourceType"], event["resourceId"]) == ("document", doc_id)
    assert event["details"]["reason"] == "not_owner"
    assert event["details"]["attempted"] == "export"
    assert event["details"]["route"] == "/api/v1/documents/{document_id}/export"


@pytest.mark.asyncio
async def test_unauthenticated_request_is_audited_as_permission_denied(
    client, owner_id, audit_sink
):
    doc_id = await _create_doc(client, owner_id)
    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=GATEWAY_HEADERS, auth=None)
    assert resp.status_code == 401

    event = await audit_sink.only("permission.denied")
    audit_sink.assert_request(
        event, user_id="anonymous", outcome="denied", ip=CLIENT_IP, request_id=REQUEST_ID
    )
    assert event["resourceId"] == doc_id
    assert event["details"]["reason"] == "unauthenticated"
    assert event["details"]["attempted"] == "delete"


@pytest.mark.asyncio
async def test_unverified_identity_headers_are_not_trusted_as_actor(client, owner_id, audit_sink):
    doc_id = await _create_doc(client, owner_id)
    forged = {**GATEWAY_HEADERS, "X-User-ID": str(owner_id), "X-User-Email": "victim@example.com"}
    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=forged, auth=None)
    assert resp.status_code == 401

    event = await audit_sink.only("permission.denied")
    audit_sink.assert_request(
        event, user_id="anonymous", outcome="denied", ip=CLIENT_IP, request_id=REQUEST_ID
    )
    assert "actorEmail" not in event


@pytest.mark.asyncio
async def test_archived_export_read_is_audited(client, owner_id, audit_sink, monkeypatch, tmp_path):
    (tmp_path / "report.md").write_text("# archived body\n", encoding="utf-8")
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(tmp_path))

    ok = await client.get(
        "/api/v1/documents/exports", params={"name": "report.md"}, headers=GATEWAY_HEADERS
    )
    missing = await client.get(
        "/api/v1/documents/exports", params={"name": "absent.md"}, headers=GATEWAY_HEADERS
    )
    assert (ok.status_code, missing.status_code) == (200, 404)

    success, failure = await audit_sink.events()
    expected = ((success, "success", "report.md"), (failure, "failure", "absent.md"))
    for event, outcome, name in expected:
        assert event["action"] == "export"
        audit_sink.assert_request(
            event, user_id=str(owner_id), outcome=outcome, ip=CLIENT_IP, request_id=REQUEST_ID
        )
        assert (event["resourceType"], event["resourceId"]) == ("export_archive", name)
    assert "archived body" not in audit_sink.requests[0].content.decode()


@pytest.mark.asyncio
async def test_document_delete_is_audited(client, owner_id, audit_sink):
    doc_id = await _create_doc(client, owner_id)
    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=GATEWAY_HEADERS)
    assert resp.status_code == 204

    event = await audit_sink.only("delete")
    audit_sink.assert_request(
        event, user_id=str(owner_id), outcome="success", ip=CLIENT_IP, request_id=REQUEST_ID
    )
    assert (event["resourceType"], event["resourceId"]) == ("document", doc_id)


@pytest.mark.asyncio
async def test_delete_of_missing_document_is_audited_as_failure(client, audit_sink):
    missing = str(uuid.uuid4())
    resp = await client.delete(f"/api/v1/documents/{missing}", headers=GATEWAY_HEADERS)
    assert resp.status_code == 404

    event = await audit_sink.only("delete")
    assert (event["outcome"], event["resourceId"]) == ("failure", missing)
    assert event["details"]["reason"] == "not_found"


@pytest.mark.asyncio
async def test_request_id_is_generated_when_gateway_sends_none(client, owner_id, audit_sink):
    doc_id = await _create_doc(client, owner_id)
    await client.delete(f"/api/v1/documents/{doc_id}", headers={"X-Real-IP": "198.51.100.9"})

    event = await audit_sink.only("delete")
    assert uuid.UUID(event["requestId"])
    assert event["ipAddress"] == "198.51.100.9"
    assert audit_sink.requests[0].headers["X-Request-ID"] == event["requestId"]


@pytest.mark.asyncio
async def test_no_secrets_are_sent_to_audit_service(client, owner_id, audit_sink):
    jwt_token = _make_jwt(str(owner_id))
    headers = {**GATEWAY_HEADERS, "Authorization": f"Bearer {jwt_token}"}
    doc_id = await _create_doc(client, owner_id, content="TOP-SECRET-DOCUMENT-BODY")
    share_token = (
        await client.post(f"/api/v1/documents/{doc_id}/share", headers=headers)
    ).json()["token"]
    await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": share_token}
    )
    await client.get(f"/api/v1/documents/{doc_id}/export", headers=headers)
    await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)

    events = await audit_sink.events()
    assert {e["action"] for e in events} == {"share.create", "share.access", "export", "delete"}
    raw = b"".join(r.content for r in audit_sink.requests).decode()
    for secret in (jwt_token, share_token, "TOP-SECRET-DOCUMENT-BODY", TEST_JWT_SECRET):
        assert secret not in raw
    forbidden = {"token", "password", "authorization", "content", "body", "jwt", "secret"}
    for event in events:
        keys = {k.lower() for k in event} | {k.lower() for k in event["details"]}
        assert not keys & forbidden


@pytest.mark.asyncio
async def test_request_succeeds_when_audit_service_returns_5xx(client, owner_id, audit_sink):
    from app.services import audit_client

    audit_sink.respond = lambda _req: httpx.Response(503)
    before = audit_client.emit_failures_total()
    doc_id = await _create_doc(client, owner_id)

    resp = await client.get(f"/api/v1/documents/{doc_id}/export", headers=GATEWAY_HEADERS)
    assert resp.status_code == 200
    assert "# Audited" in resp.text

    await audit_sink.events()
    assert len(audit_sink.requests) == audit_client.MAX_ATTEMPTS
    assert audit_client.emit_failures_total() == before + 1
    metrics = await client.get("/metrics")
    assert f"audit_emit_failures_total {before + 1}" in metrics.text


@pytest.mark.asyncio
async def test_request_succeeds_when_audit_service_times_out(client, owner_id, audit_sink):
    from app.services import audit_client

    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("audit-service timed out", request=request)

    audit_sink.respond = _timeout
    before = audit_client.emit_failures_total()
    doc_id = await _create_doc(client, owner_id)

    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=GATEWAY_HEADERS)
    assert resp.status_code == 204
    await audit_sink.events()
    assert audit_client.emit_failures_total() == before + 1
