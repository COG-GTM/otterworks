"""Folder share link API /api/v1/share-links (OTW-44, parent OTW-41).

Each test names the OTW-44 Given/When/Then scenario it covers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.main import app
from app.models.share_link import ShareLink
from app.services import share_link_repository
from app.services.file_service_client import (
    FileServiceClient,
    FileServiceError,
    FolderNotFoundError,
    get_file_service_client,
)
from app.services.share_link import ShareLinkService
from app.services.share_link_repository import WorkspaceSharePolicyRepository
from tests.conftest import TEST_JWT_SECRET

BASE = "/api/v1/share-links"


class FakeFileService:
    """Stands in for file-service: folders by id and the files inside them."""

    def __init__(self) -> None:
        self.folders: dict[uuid.UUID, dict[str, Any]] = {}
        self.files: dict[uuid.UUID, list[dict[str, Any]]] = {}
        self.down = False

    def add_folder(self, folder_id: uuid.UUID, owner_id: uuid.UUID, files: int = 0) -> None:
        now = datetime.now(UTC).isoformat()
        self.folders[folder_id] = {
            "id": str(folder_id),
            "name": "Quarterly reports",
            "parent_id": None,
            "owner_id": str(owner_id),
            "created_at": now,
            "updated_at": now,
        }
        self.files[folder_id] = [
            {
                "id": str(uuid.uuid4()),
                "name": f"report-{i}.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024 + i,
                "s3_key": f"files/{owner_id}/secret-{i}",
                "folder_id": str(folder_id),
                "owner_id": str(owner_id),
                "version": 1,
                "is_trashed": False,
                "created_at": now,
                "updated_at": now,
            }
            for i in range(files)
        ]

    async def get_folder(self, folder_id: uuid.UUID) -> dict[str, Any]:
        if self.down:
            raise FileServiceError("down")
        if folder_id not in self.folders:
            raise FolderNotFoundError(str(folder_id))
        return self.folders[folder_id]

    async def list_folder_files(self, folder_id: uuid.UUID) -> list[dict[str, Any]]:
        if self.down:
            raise FileServiceError("down")
        return self.files.get(folder_id, [])


@pytest.fixture
def files(client: AsyncClient, owner_id: uuid.UUID, folder_id: uuid.UUID) -> FakeFileService:
    fake = FakeFileService()
    fake.add_folder(folder_id, owner_id, files=2)
    app.dependency_overrides[get_file_service_client] = lambda: fake
    return fake


@pytest.fixture
def events(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    recorded: list[tuple[str, dict[str, Any]]] = []

    async def _record(event_type, link, **kwargs):
        recorded.append((event_type, {"link_id": link.id, **kwargs}))

    monkeypatch.setattr("app.api.share_links.emit_share_link_event", _record)
    return recorded


def _auth_as(user_id: uuid.UUID, **claims: Any) -> dict[str, str]:
    token = jwt.encode({"user_id": str(user_id), **claims}, TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_days_from_now(expires_at: str, days: int) -> None:
    delta = _ts(expires_at) - (datetime.now(UTC) + timedelta(days=days))
    assert abs(delta.total_seconds()) < 60


async def _link_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(ShareLink))).scalar_one()


async def _create(client: AsyncClient, folder_id: uuid.UUID, **body: Any) -> httpx.Response:
    return await client.post(
        BASE, json={"resource_type": "folder", "resource_id": str(folder_id), **body}
    )


async def _expire(db: AsyncSession, link_id: str) -> datetime:
    link = await db.get(ShareLink, uuid.UUID(link_id))
    link.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await db.commit()
    return link.expires_at


# -- Scenario 1: Given a folder the user owns, When they create a link without choosing an
# expiry, Then expires_at = now + the workspace default.


async def test_create_without_expiry_uses_builtin_default(client, files, folder_id):
    resp = await _create(client, folder_id)
    assert resp.status_code == 201
    _assert_days_from_now(resp.json()["expires_at"], 30)


async def test_create_without_expiry_uses_workspace_default(client, files, folder_id, db_session):
    await WorkspaceSharePolicyRepository(db_session).upsert(
        "default", default_days=7, max_days=14, updated_by=None
    )
    resp = await _create(client, folder_id)
    assert resp.status_code == 201
    _assert_days_from_now(resp.json()["expires_at"], 7)


async def test_default_comes_from_callers_workspace_claim(
    client, files, folder_id, owner_id, db_session
):
    await WorkspaceSharePolicyRepository(db_session).upsert(
        "ws-acme", default_days=3, max_days=10, updated_by=None
    )
    resp = await client.post(
        BASE,
        json={"resource_type": "folder", "resource_id": str(folder_id)},
        headers=_auth_as(owner_id, workspace_id="ws-acme"),
    )
    assert resp.status_code == 201
    _assert_days_from_now(resp.json()["expires_at"], 3)
    link = await db_session.get(ShareLink, uuid.UUID(resp.json()["id"]))
    assert link.workspace_id == "ws-acme"


# -- Scenario 2: Given an expiry override from 1 to 90 days within the workspace maximum,
# Then that expiry is saved on the link.


@pytest.mark.parametrize("days", [1, 45, 90])
async def test_create_with_override_saves_that_expiry(client, files, folder_id, db_session, days):
    resp = await _create(client, folder_id, expires_in_days=days)
    assert resp.status_code == 201
    _assert_days_from_now(resp.json()["expires_at"], days)
    link = await db_session.get(ShareLink, uuid.UUID(resp.json()["id"]))
    _assert_days_from_now(link.expires_at.replace(tzinfo=UTC).isoformat(), days)


async def test_patch_within_bounds_saves_new_expiry(client, files, folder_id, events):
    created = (await _create(client, folder_id, expires_in_days=5)).json()
    resp = await client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created["id"] and body["token"] == created["token"]
    _assert_days_from_now(body["expires_at"], 20)
    changed = [e for e in events if e[0] == "share_link_expiry_changed"]
    assert len(changed) == 1
    assert _ts(changed[0][1]["old_value"]["expires_at"]) == _ts(created["expires_at"])
    assert _ts(changed[0][1]["new_value"]["expires_at"]) == _ts(body["expires_at"])


# -- Scenario 3: Given an override above the workspace maximum (or "never"/null/0), When the
# link is created or edited, Then 422 and no link is created or changed.


@pytest.mark.parametrize("value", [91, 365, 0, -1, None, "never", "30", 7.5, True])
async def test_create_out_of_range_or_never_is_422_and_creates_nothing(
    client, files, folder_id, db_session, value
):
    resp = await _create(client, folder_id, expires_in_days=value)
    assert resp.status_code == 422
    assert await _link_count(db_session) == 0


async def test_create_above_workspace_max_is_422(client, files, folder_id, db_session):
    await WorkspaceSharePolicyRepository(db_session).upsert(
        "default", default_days=7, max_days=14, updated_by=None
    )
    resp = await _create(client, folder_id, expires_in_days=15)
    assert resp.status_code == 422
    assert resp.json()["detail"]["max_days"] == 14
    assert await _link_count(db_session) == 0
    assert (await _create(client, folder_id, expires_in_days=14)).status_code == 201


@pytest.mark.parametrize("value", [91, 0, None, "never"])
async def test_patch_out_of_range_or_never_is_422_and_changes_nothing(
    client, files, folder_id, db_session, value
):
    created = (await _create(client, folder_id, expires_in_days=10)).json()
    resp = await client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": value})
    assert resp.status_code == 422
    link = await db_session.get(ShareLink, uuid.UUID(created["id"]))
    await db_session.refresh(link)
    assert link.expires_at.replace(tzinfo=UTC) == _ts(created["expires_at"])


async def test_patch_above_workspace_max_is_422(client, files, folder_id, db_session):
    created = (await _create(client, folder_id, expires_in_days=10)).json()
    await WorkspaceSharePolicyRepository(db_session).upsert(
        "default", default_days=5, max_days=12, updated_by=None
    )
    resp = await client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 13})
    assert resp.status_code == 422
    link = await db_session.get(ShareLink, uuid.UUID(created["id"]))
    assert link.expires_at.replace(tzinfo=UTC) == _ts(created["expires_at"])


async def test_patch_requires_link_owner(client, files, folder_id):
    created = (await _create(client, folder_id)).json()
    resp = await client.patch(
        f"{BASE}/{created['id']}", json={"expires_in_days": 5}, headers=_auth_as(uuid.uuid4())
    )
    assert resp.status_code == 403


async def test_patch_unknown_link_is_404(client, files):
    resp = await client.patch(f"{BASE}/{uuid.uuid4()}", json={"expires_in_days": 5})
    assert resp.status_code == 404


async def test_patch_expired_link_is_410_and_not_extended(client, files, folder_id, db_session):
    created = (await _create(client, folder_id)).json()
    expired_expires_at = await _expire(db_session, created["id"])
    resp = await client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 30})
    assert resp.status_code == 410
    assert resp.json()["error"] == "link_expired"
    link = await db_session.get(ShareLink, uuid.UUID(created["id"]))
    assert link.expires_at.replace(tzinfo=UTC) == expired_expires_at


# -- Scenario 4: Given a link is created, Then a record (token, resource_type=folder,
# resource_id, workspace_id, created_by, created_at, expires_at) is saved, and the token
# comes from a CSPRNG (at least 128 bits), never an unkeyed hash.


async def test_create_saves_full_record(client, files, folder_id, owner_id, db_session, events):
    resp = await _create(client, folder_id, expires_in_days=10)
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) >= {
        "id",
        "token",
        "url",
        "resource_type",
        "resource_id",
        "expires_at",
        "created_at",
    }
    assert body["url"] == f"http://localhost:3000/s/{body['token']}"

    link = await db_session.get(ShareLink, uuid.UUID(body["id"]))
    assert link.token == body["token"]
    assert link.resource_type == "folder"
    assert link.resource_id == folder_id
    assert link.workspace_id == "default"
    assert link.created_by == owner_id
    assert link.created_at is not None and link.expires_at is not None
    assert link.expired_at is None
    assert [e[0] for e in events] == ["share_link_created"]
    assert events[0][1]["actor"] == owner_id


async def test_token_comes_from_csprng_with_at_least_128_bits(
    client, files, folder_id, monkeypatch
):
    calls: list[int] = []
    real = share_link_repository.secrets.token_urlsafe

    def _spy(nbytes: int) -> str:
        calls.append(nbytes)
        return real(nbytes)

    monkeypatch.setattr(share_link_repository.secrets, "token_urlsafe", _spy)
    first = (await _create(client, folder_id)).json()["token"]
    second = (await _create(client, folder_id)).json()["token"]

    assert calls and all(n * 8 >= 128 for n in calls)
    assert first != second
    assert len(first) >= 22  # 128 bits in url-safe base64
    legacy = ShareLinkService().mint_token(str(folder_id))
    assert legacy not in (first, second)


async def test_create_for_folder_owned_by_someone_else_is_403(client, files, db_session):
    other_folder = uuid.uuid4()
    files.add_folder(other_folder, owner_id=uuid.uuid4())
    resp = await _create(client, other_folder)
    assert resp.status_code == 403
    assert await _link_count(db_session) == 0


async def test_create_for_unknown_folder_is_404(client, files, db_session):
    resp = await _create(client, uuid.uuid4())
    assert resp.status_code == 404
    assert await _link_count(db_session) == 0


async def test_create_when_file_service_is_down_is_502(client, files, folder_id, db_session):
    files.down = True
    resp = await _create(client, folder_id)
    assert resp.status_code == 502
    assert await _link_count(db_session) == 0


async def test_create_requires_authentication(client, files, folder_id):
    resp = await client.post(
        BASE, json={"resource_type": "folder", "resource_id": str(folder_id)}, auth=None
    )
    assert resp.status_code == 401


async def test_create_rejects_non_folder_resources(client, files, folder_id):
    resp = await client.post(
        BASE, json={"resource_type": "document", "resource_id": str(folder_id)}
    )
    assert resp.status_code == 422


async def test_list_returns_only_callers_links_for_resource(client, files, folder_id, owner_id):
    mine = [(await _create(client, folder_id)).json()["id"] for _ in range(2)]
    other_user = uuid.uuid4()
    files.folders[folder_id]["owner_id"] = str(other_user)
    await client.post(
        BASE,
        json={"resource_type": "folder", "resource_id": str(folder_id)},
        headers=_auth_as(other_user),
    )
    resp = await client.get(BASE, params={"resource_id": str(folder_id)})
    assert resp.status_code == 200
    assert sorted(link["id"] for link in resp.json()) == sorted(mine)
    empty = await client.get(BASE, params={"resource_id": str(uuid.uuid4())})
    assert empty.json() == []


async def test_url_uses_public_app_url_setting(client, files, folder_id, monkeypatch):
    monkeypatch.setattr(settings, "public_app_url", "https://app.example.com/")
    body = (await _create(client, folder_id)).json()
    assert body["url"] == f"https://app.example.com/s/{body['token']}"


def test_public_app_url_reads_env(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://otterworks.example")
    assert Settings().public_app_url == "https://otterworks.example"
    monkeypatch.delenv("PUBLIC_APP_URL")
    assert Settings().public_app_url == "http://localhost:3000"


# -- Scenario 5: Given a valid link, When it is opened, Then the folder contents are listed
# read-only (document-service calls file-service for folder metadata and file list) and
# nothing can be written.


async def test_resolve_lists_folder_read_only_without_auth(client, files, folder_id):
    created = (await _create(client, folder_id, expires_in_days=3)).json()
    resp = await client.get(f"{BASE}/resolve/{created['token']}", auth=None)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["resource_type"] == "folder"
    assert body["folder"]["id"] == str(folder_id)
    assert body["folder"]["name"] == "Quarterly reports"
    assert _ts(body["expires_at"]) == _ts(created["expires_at"])
    assert [f["name"] for f in body["files"]] == ["report-0.pdf", "report-1.pdf"]
    for item in [body["folder"], *body["files"]]:
        assert "owner_id" not in item and "s3_key" not in item


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_resolve_route_accepts_no_writes(client, files, folder_id, method):
    token = (await _create(client, folder_id)).json()["token"]
    resp = await client.request(method, f"{BASE}/resolve/{token}", auth=None, json={})
    assert resp.status_code == 405


async def test_resolve_unknown_token_is_404(client, files):
    resp = await client.get(f"{BASE}/resolve/not-a-real-token", auth=None)
    assert resp.status_code == 404


async def test_resolve_deleted_folder_is_404(client, files, folder_id):
    token = (await _create(client, folder_id)).json()["token"]
    del files.folders[folder_id]
    resp = await client.get(f"{BASE}/resolve/{token}", auth=None)
    assert resp.status_code == 404


async def test_resolve_when_file_service_is_down_is_502(client, files, folder_id):
    token = (await _create(client, folder_id)).json()["token"]
    files.down = True
    assert (await client.get(f"{BASE}/resolve/{token}", auth=None)).status_code == 502


# -- Scenario 6: Given a link whose expires_at has passed, When it is opened, Then HTTP 410
# and expired_at is set once (mark_expired). The expiry is never extended automatically.


async def test_resolve_expired_link_is_410_and_marks_expired_once(
    client, files, folder_id, db_session, events
):
    created = (await _create(client, folder_id)).json()
    expires_at = await _expire(db_session, created["id"])

    first = await client.get(f"{BASE}/resolve/{created['token']}", auth=None)
    assert first.status_code == 410
    assert first.json()["error"] == "link_expired"
    first_expired_at = first.json()["expired_at"]
    assert first_expired_at is not None

    second = await client.get(f"{BASE}/resolve/{created['token']}", auth=None)
    assert second.status_code == 410
    assert second.json()["expired_at"] == first_expired_at

    link = await db_session.get(ShareLink, uuid.UUID(created["id"]))
    await db_session.refresh(link)
    assert link.expired_at.replace(tzinfo=UTC) == _ts(first_expired_at)
    assert link.expires_at.replace(tzinfo=UTC) == expires_at
    expired_events = [e for e in events if e[0] == "share_link_expired"]
    assert len(expired_events) == 1
    assert expired_events[0][1]["actor"] is None


async def test_expired_link_is_shown_in_owners_list(client, files, folder_id, db_session):
    created = (await _create(client, folder_id)).json()
    await _expire(db_session, created["id"])
    await client.get(f"{BASE}/resolve/{created['token']}", auth=None)
    listed = (await client.get(BASE, params={"resource_id": str(folder_id)})).json()
    assert listed[0]["expired_at"] is not None


# -- Scenario 7: Given a document share token that existed before release, When it is opened
# via the existing GET /api/v1/documents/shared, Then it still works with no expiry.


async def test_legacy_document_share_token_still_works(client, files, owner_id, db_session):
    doc = (
        await client.post(
            "/api/v1/documents/",
            json={"title": "Old", "content": "body", "owner_id": str(owner_id)},
        )
    ).json()
    legacy_token = ShareLinkService().mint_token(doc["id"])

    resp = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc["id"], "token": legacy_token},
        auth=None,
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == doc["id"]
    assert await _link_count(db_session) == 0
    resolve = await client.get(f"{BASE}/resolve/{legacy_token}", auth=None)
    assert resolve.status_code == 404


# -- FileServiceClient: the read-only file-service calls behind scenarios 4 and 5.


def _client_with(handler) -> FileServiceClient:
    return FileServiceClient("http://file-service:8082", transport=httpx.MockTransport(handler))


async def test_file_service_client_pages_through_folder_files():
    folder = uuid.uuid4()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        page = int(request.url.params["page"])
        batch = [{"id": str(uuid.uuid4()), "name": f"f{page}-{i}"} for i in range(100)]
        return httpx.Response(200, json={"files": batch if page < 3 else batch[:5], "total": 205})

    result = await _client_with(handler).list_folder_files(folder)
    assert len(result) == 205
    assert [int(r.url.params["page"]) for r in seen] == [1, 2, 3]
    for request in seen:
        assert request.url.path == "/api/v1/files"
        assert request.url.params["folder_id"] == str(folder)
        assert "owner_id" not in request.url.params
        assert "x-user-id" not in request.headers


async def test_file_service_client_drops_rows_repeated_across_pages():
    folder = uuid.uuid4()
    first = [{"id": str(uuid.uuid4()), "name": f"a{i}"} for i in range(100)]
    shifted = [first[-1], {"id": str(uuid.uuid4()), "name": "b0"}]

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"files": first if page == 1 else shifted, "total": 102})

    result = await _client_with(handler).list_folder_files(folder)
    ids = [f["id"] for f in result]
    assert len(ids) == len(set(ids)) == 101


async def test_file_service_client_folder_lookup():
    folder = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v1/folders/{folder}":
            return httpx.Response(200, json={"id": str(folder), "owner_id": "u"})
        if request.url.path.startswith("/api/v1/folders/"):
            return httpx.Response(404, json={"error": "folder_not_found"})
        return httpx.Response(500)

    client = _client_with(handler)
    assert (await client.get_folder(folder))["id"] == str(folder)
    with pytest.raises(FolderNotFoundError):
        await client.get_folder(uuid.uuid4())
    with pytest.raises(FileServiceError):
        await client.list_folder_files(folder)


async def test_file_service_client_wraps_connection_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(FileServiceError):
        await _client_with(handler).get_folder(uuid.uuid4())
