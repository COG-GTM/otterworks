"""OTW-33: folder share link API (OTW-29 Stories 2, 3 and 4)."""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app
from app.models.share import FolderShareLink, WorkspaceSharePolicy
from app.services.folder_directory import (
    FileServiceFolderDirectory,
    FolderInfo,
    FolderLookupError,
    get_folder_directory,
)
from app.services.share_audit import get_share_audit_publisher
from tests.conftest import TEST_JWT_SECRET

HMAC_KEY = "test-share-link-hmac-key"
DAY = 24 * 3600


class FakeFolders:
    def __init__(self) -> None:
        self.folders: dict[uuid.UUID, FolderInfo] = {}
        self.fail = False

    def add(self, folder_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        self.folders[folder_id] = FolderInfo(id=folder_id, owner_id=owner_id)

    async def get_folder(self, folder_id: uuid.UUID) -> FolderInfo | None:
        if self.fail:
            raise FolderLookupError("down")
        return self.folders.get(folder_id)


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event_type, actor_id, workspace_id, resource_type, resource_id,
                   old_value, new_value) -> None:
        self.events.append({
            "event_type": event_type, "actor_id": actor_id, "workspace_id": workspace_id,
            "resource_type": resource_type, "resource_id": resource_id,
            "old_value": old_value, "new_value": new_value,
        })

    def of(self, event_type: str) -> list[dict]:
        return [e for e in self.events if e["event_type"] == event_type]


@pytest.fixture
def folders(owner_id: uuid.UUID, folder_id: uuid.UUID) -> FakeFolders:
    fake = FakeFolders()
    fake.add(folder_id, owner_id)
    return fake


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit()


@pytest.fixture(autouse=True)
def _wire(monkeypatch: pytest.MonkeyPatch, folders: FakeFolders, audit: RecordingAudit):
    monkeypatch.setattr(settings, "share_link_hmac_key", HMAC_KEY)
    monkeypatch.setattr(settings, "public_web_url", "https://app.example.test")
    monkeypatch.setattr(settings, "share_policy_owner_ids", "")
    app.dependency_overrides[get_folder_directory] = lambda: folders
    app.dependency_overrides[get_share_audit_publisher] = lambda: audit
    yield
    app.dependency_overrides.pop(get_folder_directory, None)
    app.dependency_overrides.pop(get_share_audit_publisher, None)


def _auth(user_id: uuid.UUID, roles: list[str] | None = None) -> dict[str, str]:
    claims: dict = {"user_id": str(user_id)}
    if roles:
        claims["roles"] = roles
    return {"Authorization": f"Bearer {jwt.encode(claims, TEST_JWT_SECRET, algorithm='HS256')}"}


async def _save_policy(db: AsyncSession, **overrides) -> None:
    values = {"default_expiry_seconds": 30 * DAY, "min_expiry_seconds": 3600,
              "max_expiry_seconds": 90 * DAY, "allow_never": False, **overrides}
    db.add(WorkspaceSharePolicy(workspace_id=settings.workspace_id, **values))
    await db.commit()


async def _create_link(client: AsyncClient, folder_id: uuid.UUID, **body) -> dict:
    resp = await client.post(f"/api/v1/documents/folders/{folder_id}/share-links", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_doc(client: AsyncClient, owner_id, folder_id, title="Doc") -> dict:
    resp = await client.post("/api/v1/documents/", json={
        "title": title, "content": f"{title} body", "owner_id": str(owner_id),
        "folder_id": str(folder_id) if folder_id else None,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _expire(db: AsyncSession, link_id: str) -> datetime:
    past = datetime.now(UTC) - timedelta(minutes=5)
    await db.execute(update(FolderShareLink)
                     .where(FolderShareLink.id == uuid.UUID(link_id)).values(expires_at=past))
    await db.commit()
    return past


def _parse(ts: str) -> datetime:
    value = datetime.fromisoformat(ts)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ---- Story 2: create ----


async def test_create_without_override_uses_workspace_default(
    client: AsyncClient, db_session: AsyncSession, owner_id, folder_id, audit
):
    data = await _create_link(client, folder_id)

    expected = datetime.now(UTC) + timedelta(days=30)
    assert abs(_parse(data["expires_at"]) - expected) < timedelta(minutes=1)
    assert data["folder_id"] == str(folder_id)
    assert data["created_by"] == str(owner_id)
    assert data["status"] == "active"
    assert data["url"] == f"https://app.example.test/shared-folder/{data['token']}"

    link = (await db_session.execute(select(FolderShareLink))).scalar_one()
    assert link.workspace_id == settings.workspace_id
    assert link.created_at is not None
    assert link.token_hash == hmac.new(
        HMAC_KEY.encode(), data["token"].encode(), hashlib.sha256).hexdigest()
    assert data["token"] not in link.token_hash

    [event] = audit.of("share_link_created")
    assert event["actor_id"] == str(owner_id)
    assert event["resource_type"] == "share_link"
    assert event["resource_id"] == data["id"]
    assert event["new_value"]["folder_id"] == str(folder_id)
    assert event["new_value"]["expires_at"] is not None


async def test_tokens_are_csprng_and_unique(client: AsyncClient, folder_id):
    first = await _create_link(client, folder_id)
    second = await _create_link(client, folder_id)
    # token_urlsafe(32) -> 43 url-safe chars, 256 bits.
    assert len(first["token"]) >= 43
    assert first["token"] != second["token"]


async def test_override_within_policy_is_applied(client, db_session, folder_id):
    await _save_policy(db_session)
    data = await _create_link(client, folder_id, expires_in_seconds=30 * DAY)
    expected = datetime.now(UTC) + timedelta(days=30)
    assert abs(_parse(data["expires_at"]) - expected) < timedelta(minutes=1)


@pytest.mark.parametrize("seconds", [120 * DAY, 30 * 60])
async def test_override_outside_policy_is_422_with_range(client, db_session, folder_id, seconds):
    await _save_policy(db_session)
    resp = await client.post(
        f"/api/v1/documents/folders/{folder_id}/share-links",
        json={"expires_in_seconds": seconds},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["min_expiry_seconds"] == 3600
    assert body["max_expiry_seconds"] == 90 * DAY
    assert body["allow_never"] is False
    assert (await db_session.execute(select(FolderShareLink))).first() is None


async def test_never_rejected_when_policy_disallows(client, db_session, folder_id):
    await _save_policy(db_session, allow_never=False)
    resp = await client.post(
        f"/api/v1/documents/folders/{folder_id}/share-links", json={"never": True})
    assert resp.status_code == 422
    assert resp.json()["allow_never"] is False


async def test_never_allowed_gives_null_expiry(client, db_session, folder_id):
    await _save_policy(db_session, allow_never=True)
    data = await _create_link(client, folder_id, never=True)
    assert data["expires_at"] is None
    assert data["status"] == "active"


async def test_create_by_non_owner_is_403(client, folder_id):
    resp = await client.post(
        f"/api/v1/documents/folders/{folder_id}/share-links", headers=_auth(uuid.uuid4()))
    assert resp.status_code == 403


async def test_create_for_unknown_folder_is_404(client):
    resp = await client.post(f"/api/v1/documents/folders/{uuid.uuid4()}/share-links")
    assert resp.status_code == 404


async def test_create_requires_authentication(client, folder_id):
    resp = await client.post(
        f"/api/v1/documents/folders/{folder_id}/share-links", auth=None)
    assert resp.status_code == 401


async def test_file_service_failure_is_502(client, folders, folder_id):
    folders.fail = True
    resp = await client.post(f"/api/v1/documents/folders/{folder_id}/share-links")
    assert resp.status_code == 502


# ---- Story 3: recipient access ----


async def test_recipient_lists_and_reads_folder_documents(client, owner_id, folder_id):
    in_folder = await _create_doc(client, owner_id, folder_id, "In folder")
    deleted = await _create_doc(client, owner_id, folder_id, "Deleted")
    await client.delete(f"/api/v1/documents/{deleted['id']}")
    outside = await _create_doc(client, owner_id, uuid.uuid4(), "Elsewhere")
    token = (await _create_link(client, folder_id))["token"]

    listing = await client.get(f"/api/v1/documents/shared-folders/{token}", auth=None)
    assert listing.status_code == 200
    body = listing.json()
    assert body["folder_id"] == str(folder_id)
    assert body["expires_at"] is not None
    assert [d["id"] for d in body["documents"]] == [in_folder["id"]]
    assert set(body["documents"][0]) == {"id", "title", "updated_at"}

    doc = await client.get(
        f"/api/v1/documents/shared-folders/{token}/documents/{in_folder['id']}", auth=None)
    assert doc.status_code == 200
    assert doc.json()["content"] == "In folder body"

    for other in (outside["id"], deleted["id"], str(uuid.uuid4())):
        resp = await client.get(
            f"/api/v1/documents/shared-folders/{token}/documents/{other}", auth=None)
        assert resp.status_code == 404


async def test_recipient_routes_are_read_only(client, owner_id, folder_id):
    doc = await _create_doc(client, owner_id, folder_id)
    token = (await _create_link(client, folder_id))["token"]
    path = f"/api/v1/documents/shared-folders/{token}/documents/{doc['id']}"
    for method in ("PUT", "PATCH", "DELETE", "POST"):
        resp = await client.request(method, path, json={}, auth=None)
        assert resp.status_code == 405


async def test_expired_link_is_410_and_audited_once(
    client, db_session, owner_id, folder_id, audit
):
    doc = await _create_doc(client, owner_id, folder_id)
    created = await _create_link(client, folder_id)
    past = await _expire(db_session, created["id"])
    token = created["token"]

    folder_resp = await client.get(f"/api/v1/documents/shared-folders/{token}", auth=None)
    doc_resp = await client.get(
        f"/api/v1/documents/shared-folders/{token}/documents/{doc['id']}", auth=None)
    assert folder_resp.status_code == doc_resp.status_code == 410
    assert folder_resp.json()["detail"] == "Share link expired"

    [event] = audit.of("share_link_expired")
    assert event["actor_id"] is None
    assert event["resource_id"] == created["id"]
    link = await db_session.get(FolderShareLink, uuid.UUID(created["id"]))
    await db_session.refresh(link)
    assert link.expired_audited_at is not None
    # Never extended silently.
    assert abs(_parse(link.expires_at.isoformat()) - past) < timedelta(seconds=1)


async def test_revoked_link_is_410(client, owner_id, folder_id, audit):
    doc = await _create_doc(client, owner_id, folder_id)
    created = await _create_link(client, folder_id)
    assert (await client.delete(
        f"/api/v1/documents/share-links/{created['id']}")).status_code == 204
    assert (await client.delete(
        f"/api/v1/documents/share-links/{created['id']}")).status_code == 204

    token = created["token"]
    folder_resp = await client.get(f"/api/v1/documents/shared-folders/{token}", auth=None)
    doc_resp = await client.get(
        f"/api/v1/documents/shared-folders/{token}/documents/{doc['id']}", auth=None)
    assert folder_resp.status_code == doc_resp.status_code == 410
    assert folder_resp.json()["detail"] == "Share link revoked"
    [event] = audit.of("share_link_revoked")
    assert event["old_value"]["revoked_at"] is None
    assert event["new_value"]["revoked_at"] is not None


async def test_unknown_token_is_404(client):
    for token in ("not-a-real-token", "x" * 500):
        resp = await client.get(f"/api/v1/documents/shared-folders/{token}", auth=None)
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Share link not found"}


# ---- Story 4: change / revoke / list ----


async def test_creator_updates_expiry_within_policy(client, db_session, owner_id, folder_id, audit):
    await _save_policy(db_session)
    created = await _create_link(client, folder_id)
    resp = await client.patch(
        f"/api/v1/documents/share-links/{created['id']}", json={"expires_in_seconds": 7 * DAY})
    assert resp.status_code == 200
    expected = datetime.now(UTC) + timedelta(days=7)
    assert abs(_parse(resp.json()["expires_at"]) - expected) < timedelta(minutes=1)
    [event] = audit.of("share_link_updated")
    assert event["actor_id"] == str(owner_id)
    assert event["old_value"]["expires_at"] != event["new_value"]["expires_at"]

    too_long = await client.patch(
        f"/api/v1/documents/share-links/{created['id']}", json={"expires_in_seconds": 120 * DAY})
    assert too_long.status_code == 422
    assert too_long.json()["max_expiry_seconds"] == 90 * DAY


@pytest.mark.parametrize("via", ["role", "allowlist"])
async def test_workspace_owner_can_update_and_others_cannot(
    client, monkeypatch, folder_id, via
):
    created = await _create_link(client, folder_id)
    path = f"/api/v1/documents/share-links/{created['id']}"
    body = {"expires_in_seconds": 2 * DAY}

    stranger = await client.patch(path, json=body, headers=_auth(uuid.uuid4()))
    assert stranger.status_code == 403
    assert (await client.delete(path, headers=_auth(uuid.uuid4()))).status_code == 403

    ws_owner = uuid.uuid4()
    if via == "allowlist":
        monkeypatch.setattr(settings, "share_policy_owner_ids", f"{uuid.uuid4()},{ws_owner}")
        headers = _auth(ws_owner)
    else:
        headers = _auth(ws_owner, roles=["ADMIN"])
    assert (await client.patch(path, json=body, headers=headers)).status_code == 200
    assert (await client.delete(path, headers=headers)).status_code == 204


async def test_extending_expired_or_revoked_link_is_409(client, db_session, folder_id):
    expired = await _create_link(client, folder_id)
    await _expire(db_session, expired["id"])
    revoked = await _create_link(client, folder_id)
    await client.delete(f"/api/v1/documents/share-links/{revoked['id']}")

    for link_id, state in ((expired["id"], "expired"), (revoked["id"], "revoked")):
        resp = await client.patch(
            f"/api/v1/documents/share-links/{link_id}", json={"expires_in_seconds": DAY})
        assert resp.status_code == 409
        assert state in resp.json()["detail"]


async def test_update_unknown_link_is_404(client):
    resp = await client.patch(
        f"/api/v1/documents/share-links/{uuid.uuid4()}", json={"expires_in_seconds": DAY})
    assert resp.status_code == 404


async def test_owner_lists_links_with_status(client, db_session, owner_id, folder_id):
    active = await _create_link(client, folder_id)
    expired = await _create_link(client, folder_id)
    await _expire(db_session, expired["id"])
    revoked = await _create_link(client, folder_id)
    await client.delete(f"/api/v1/documents/share-links/{revoked['id']}")

    resp = await client.get(f"/api/v1/documents/folders/{folder_id}/share-links")
    assert resp.status_code == 200
    items = {item["id"]: item for item in resp.json()["items"]}
    assert {k: v["status"] for k, v in items.items()} == {
        active["id"]: "active", expired["id"]: "expired", revoked["id"]: "revoked"}
    for item in items.values():
        assert item["created_by"] == str(owner_id)
        assert item["created_at"]
        assert "expires_at" in item
        assert "token" not in item

    other = await client.get(
        f"/api/v1/documents/folders/{folder_id}/share-links", headers=_auth(uuid.uuid4()))
    assert other.status_code == 403
    missing = await client.get(f"/api/v1/documents/folders/{uuid.uuid4()}/share-links")
    assert missing.status_code == 404


# ---- Compatibility ----


async def test_existing_document_routes_do_not_collide(client, owner_id, folder_id):
    doc = await _create_doc(client, owner_id, folder_id)
    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 200
    minted = await client.post(f"/api/v1/documents/{doc['id']}/share")
    assert minted.status_code == 200
    shared = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc["id"], "token": minted.json()["token"]},
    )
    assert shared.status_code == 200
    assert shared.json()["id"] == doc["id"]


# ---- file-service client ----


async def test_file_service_folder_directory():
    folder_id, owner = uuid.uuid4(), uuid.uuid4()
    missing = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v1/folders/{folder_id}":
            return httpx.Response(200, json={"id": str(folder_id), "owner_id": str(owner),
                                             "name": "F", "parent_id": None})
        if request.url.path == f"/api/v1/folders/{missing}":
            return httpx.Response(404, json={"error": "folder_not_found"})
        return httpx.Response(500)

    directory = FileServiceFolderDirectory(
        "http://file-service:8082/", transport=httpx.MockTransport(handler))
    assert await directory.get_folder(folder_id) == FolderInfo(id=folder_id, owner_id=owner)
    assert await directory.get_folder(missing) is None
    with pytest.raises(FolderLookupError):
        await directory.get_folder(uuid.uuid4())
