"""Authentication, chaos-injection and error paths of the documents API."""

import uuid
from unittest.mock import MagicMock

import jwt
import pytest
from httpx import AsyncClient

import app.api.documents as documents
from tests.conftest import TEST_JWT_SECRET


def _bearer(user_id: uuid.UUID) -> str:
    return "Bearer " + jwt.encode(
        {"user_id": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256"
    )


async def _create_document(client: AsyncClient, owner_id: uuid.UUID) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Doc", "content": "Body", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ---- Redis-backed chaos flags ----


def test_get_redis_client_is_created_once(monkeypatch):
    monkeypatch.setattr(documents, "_redis_client", None)
    constructed: list[dict] = []
    monkeypatch.setattr(
        documents.redis_lib,
        "Redis",
        lambda **kwargs: constructed.append(kwargs) or MagicMock(name="redis"),
    )
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")

    first = documents._get_redis()
    second = documents._get_redis()

    assert first is second
    assert constructed == [
        {
            "host": "redis.internal",
            "port": 6380,
            "decode_responses": True,
            "socket_timeout": 1,
        }
    ]


def test_chaos_active_reflects_key_presence(monkeypatch):
    redis = MagicMock()
    redis.exists.return_value = 1
    monkeypatch.setattr(documents, "_get_redis", lambda: redis)

    assert documents._chaos_active("chaos:document-service:slow_queries") is True
    redis.exists.assert_called_once_with("chaos:document-service:slow_queries")


def test_chaos_active_is_false_when_redis_is_unreachable(monkeypatch):
    redis = MagicMock()
    redis.exists.side_effect = ConnectionError("redis down")
    monkeypatch.setattr(documents, "_get_redis", lambda: redis)

    assert documents._chaos_active("chaos:document-service:slow_queries") is False


@pytest.mark.asyncio
async def test_slow_queries_flag_injects_latency(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch
):
    checked: list[str] = []
    delays: list[float] = []

    def _chaos_active(key: str) -> bool:
        checked.append(key)
        return True

    async def _sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(documents, "_chaos_active", _chaos_active)
    monkeypatch.setattr(documents.random, "uniform", lambda low, high: low)
    monkeypatch.setattr(documents.asyncio, "sleep", _sleep)

    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Slow", "content": "Body", "owner_id": str(owner_id)},
    )

    assert resp.status_code == 201
    assert checked == ["chaos:document-service:slow_queries"]
    assert delays == [3.0]


# ---- Authentication ----


@pytest.mark.asyncio
async def test_request_without_authorization_header_is_rejected(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}", auth=None)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Authentication required"


@pytest.mark.asyncio
async def test_non_bearer_authorization_scheme_is_rejected(client: AsyncClient):
    resp = await client.get(
        f"/api/v1/documents/{uuid.uuid4()}", headers={"Authorization": "Basic dXNlcg=="}
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unverifiable_token_is_rejected(client: AsyncClient):
    resp = await client.get(
        f"/api/v1/documents/{uuid.uuid4()}",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_with_non_uuid_subject_is_rejected(client: AsyncClient):
    token = jwt.encode({"sub": "not-a-uuid"}, TEST_JWT_SECRET, algorithm="HS256")

    resp = await client.get(
        f"/api/v1/documents/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_without_identity_claims_is_rejected(client: AsyncClient):
    token = jwt.encode({"scope": "documents"}, TEST_JWT_SECRET, algorithm="HS256")

    resp = await client.get(
        f"/api/v1/documents/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sub_claim_identifies_the_caller(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)
    token = jwt.encode({"sub": str(owner_id)}, TEST_JWT_SECRET, algorithm="HS256")

    resp = await client.get(
        f"/api/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_x_user_id_header_is_trusted_when_no_jwt_secret_is_configured(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch
):
    monkeypatch.setattr(documents, "_get_jwt_secret", lambda: "")

    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Gateway forwarded", "content": "Body"},
        headers={"Authorization": "Bearer opaque", "X-User-ID": str(owner_id)},
    )

    assert resp.status_code == 201
    assert resp.json()["owner_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_malformed_x_user_id_header_is_rejected(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(documents, "_get_jwt_secret", lambda: "")

    resp = await client.get(
        f"/api/v1/documents/{uuid.uuid4()}",
        headers={"Authorization": "Bearer opaque", "X-User-ID": "nope"},
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bearer_token_without_secret_or_forwarded_header_is_rejected(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(documents, "_get_jwt_secret", lambda: "")

    resp = await client.get(
        f"/api/v1/documents/{uuid.uuid4()}", headers={"Authorization": "Bearer opaque"}
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_without_owner_or_identity_is_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/documents/", json={"title": "Orphan", "content": "Body"}, auth=None
    )

    assert resp.status_code == 401
    assert "owner_id is required" in resp.json()["detail"]


# ---- Ownership ----


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("put", "", {"title": "Hijacked", "content": "Body"}),
        ("patch", "", {"title": "Hijacked"}),
        ("delete", "", None),
        ("get", "/versions", None),
        ("get", "/export", None),
    ],
)
@pytest.mark.asyncio
async def test_another_user_cannot_touch_the_document(
    client: AsyncClient, owner_id: uuid.UUID, method: str, suffix: str, body: dict | None
):
    doc_id = await _create_document(client, owner_id)
    intruder = {"Authorization": _bearer(uuid.uuid4())}

    kwargs = {"headers": intruder}
    if body is not None:
        kwargs["json"] = body
    resp = await getattr(client, method)(f"/api/v1/documents/{doc_id}{suffix}", **kwargs)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Access denied"


@pytest.mark.asyncio
async def test_another_user_cannot_restore_a_version(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)
    versions = await client.get(f"/api/v1/documents/{doc_id}/versions")
    version_id = versions.json()[0]["id"]

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/versions/{version_id}/restore",
        headers={"Authorization": _bearer(uuid.uuid4())},
    )

    assert resp.status_code == 403


# ---- Missing documents ----


@pytest.mark.asyncio
async def test_update_missing_document_returns_404(client: AsyncClient):
    resp = await client.put(
        f"/api/v1/documents/{uuid.uuid4()}", json={"title": "Ghost", "content": "Body"}
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_missing_document_returns_404(client: AsyncClient):
    resp = await client.patch(
        f"/api/v1/documents/{uuid.uuid4()}", json={"title": "Ghost"}
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_missing_document_returns_404(client: AsyncClient):
    resp = await client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_versions_of_missing_document_returns_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}/versions")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_missing_document_returns_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}/export")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_on_missing_document_returns_404(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/documents/{uuid.uuid4()}/versions/{uuid.uuid4()}/restore"
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_unknown_version_returns_404(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/versions/{uuid.uuid4()}/restore"
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Document or version not found"


# ---- Routes registered without a trailing slash ----


@pytest.mark.asyncio
async def test_create_and_list_without_trailing_slash(
    client: AsyncClient, owner_id: uuid.UUID
):
    created = await client.post(
        "/api/v1/documents",
        json={"title": "No slash", "content": "Body", "owner_id": str(owner_id)},
    )
    assert created.status_code == 201

    listed = await client.get("/api/v1/documents")

    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "No slash"


@pytest.mark.asyncio
async def test_list_without_trailing_slash_filters_by_authenticated_user(
    client: AsyncClient, owner_id: uuid.UUID
):
    await _create_document(client, owner_id)

    listed = await client.get(
        "/api/v1/documents", headers={"Authorization": _bearer(uuid.uuid4())}
    )

    assert listed.status_code == 200
    assert listed.json()["total"] == 0


@pytest.mark.asyncio
async def test_export_defaults_to_pdf_representation(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)

    resp = await client.get(f"/api/v1/documents/{doc_id}/export", params={"format": "pdf"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.text == "TITLE: Doc\n\nBody"
