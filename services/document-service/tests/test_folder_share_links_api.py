"""OTW-67 folder share-link API tests.

Each test is named after the OTW-63 Given/When/Then scenario it covers (US1, US3,
US4 and "expiry is never silently extended"). file-service and the sharing policy
are replaced with in-memory fakes through FastAPI dependency overrides.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import folder_share_links as api
from app.main import app
from app.models.folder_share_link import FolderShareLink
from app.services.file_service_client import (
    FileServiceUnavailableError,
    FolderFile,
    FolderInfo,
    get_file_service_client,
)
from app.services.folder_share_link_events import ShareLinkEventType
from app.services.folder_share_token import hash_token
from app.services.sharing_policy import (
    FALLBACK_POLICY,
    SharingPolicy,
    get_sharing_policy_client,
)
from tests.conftest import bearer_auth

BASE = "/api/v1/folder-share-links"
SECRET = "test-share-link-secret"  # noqa: S105
DAY = timedelta(days=1)


class FakeFileService:
    def __init__(self) -> None:
        self.folders: dict[uuid.UUID, FolderInfo] = {}
        self.files: dict[uuid.UUID, list[FolderFile]] = {}
        self.unavailable = False
        self.acting_users: list[uuid.UUID] = []

    def add_folder(self, folder_id: uuid.UUID, owner_id: uuid.UUID, name: str = "Q4 Reports"):
        self.folders[folder_id] = FolderInfo(id=folder_id, name=name, owner_id=owner_id)

    async def get_folder(
        self, folder_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> FolderInfo | None:
        self.acting_users.append(acting_user_id)
        if self.unavailable:
            raise FileServiceUnavailableError("down")
        return self.folders.get(folder_id)

    async def list_folder_files(self, folder: FolderInfo) -> list[FolderFile]:
        if self.unavailable:
            raise FileServiceUnavailableError("down")
        return self.files.get(folder.id, [])


class FakePolicyClient:
    def __init__(self) -> None:
        self.policy: SharingPolicy = FALLBACK_POLICY
        self.authorizations: list[str | None] = []

    async def get_policy(self, authorization: str | None = None) -> SharingPolicy:
        self.authorizations.append(authorization)
        return self.policy


@pytest.fixture(autouse=True)
def share_link_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARE_LINK_SECRET", SECRET)


@pytest.fixture
def file_service(owner_id: uuid.UUID, folder_id: uuid.UUID) -> FakeFileService:
    fake = FakeFileService()
    fake.add_folder(folder_id, owner_id)
    return fake


@pytest.fixture
def policy_client() -> FakePolicyClient:
    return FakePolicyClient()


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    async def record(event_type, link, actor_id, old_value=None, new_value=None):
        calls.append((event_type, link.id, actor_id, old_value, new_value))

    monkeypatch.setattr(api, "emit_share_link_event", record)
    return calls


@pytest.fixture
async def api_client(
    client: AsyncClient, file_service: FakeFileService, policy_client: FakePolicyClient
) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_file_service_client] = lambda: file_service
    app.dependency_overrides[get_sharing_policy_client] = lambda: policy_client
    yield client


async def _create(api_client: AsyncClient, folder_id: uuid.UUID, **body) -> dict:
    resp = await api_client.post(BASE, json={"folder_id": str(folder_id), **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _link_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(FolderShareLink))).scalar_one()


async def _load(db: AsyncSession, link_id: str) -> FolderShareLink:
    db.expire_all()
    link = await db.get(FolderShareLink, uuid.UUID(link_id))
    assert link is not None
    return link


async def _age_link(db: AsyncSession, link_id: str, *, created_ago: timedelta, lifetime: timedelta):
    """Move a link back in time: created ``created_ago`` ago, expiring ``lifetime`` later."""
    link = await _load(db, link_id)
    link.created_at = datetime.now(UTC) - created_ago
    link.expires_at = link.created_at + lifetime
    await db.commit()


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- US1: Create folder share link -------------------------------------------------


# US1 / Given I own folder F, When I create a share link without picking an expiry,
# Then a record is saved with token, folder_id, workspace, created_by, created_at and
# expires_at = created_at + workspace default (30 days unless changed).
async def test_us1_owner_creates_link_with_default_30_day_expiry(
    api_client: AsyncClient, db_session: AsyncSession, owner_id, folder_id
):
    data = await _create(api_client, folder_id)

    assert set(data) == {"id", "folder_id", "token", "expires_at", "created_at"}
    assert data["folder_id"] == str(folder_id)
    assert _ts(data["expires_at"]) - _ts(data["created_at"]) == timedelta(days=30)

    link = await _load(db_session, data["id"])
    assert link.folder_id == folder_id
    assert link.workspace_id == "default"
    assert link.created_by == owner_id
    assert link.revoked_at is None


# US1 / ... expires_at = created_at + workspace default (when the workspace owner changed it)
async def test_us1_default_expiry_follows_workspace_policy(
    api_client: AsyncClient, policy_client: FakePolicyClient, folder_id
):
    policy_client.policy = SharingPolicy(default_expiry_days=14, min_expiry_days=1,
                                         max_expiry_days=30)
    data = await _create(api_client, folder_id)
    assert _ts(data["expires_at"]) - _ts(data["created_at"]) == timedelta(days=14)
    # The policy is read on behalf of the caller (the management service authenticates it).
    assert policy_client.authorizations[-1].startswith("Bearer ")


# US1 / Given I do not own folder F, When I try to create a share link,
# Then the request is rejected with 403 and no record is created.
async def test_us1_non_owner_gets_403_and_no_record(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    resp = await api_client.post(
        BASE, json={"folder_id": str(folder_id)}, auth=bearer_auth(uuid.uuid4())
    )
    assert resp.status_code == 403
    assert await _link_count(db_session) == 0


# US1 / non-owner variant: a folder file-service does not know is not owned by the caller.
async def test_us1_unknown_folder_gets_403_and_no_record(
    api_client: AsyncClient, db_session: AsyncSession
):
    resp = await api_client.post(BASE, json={"folder_id": str(uuid.uuid4())})
    assert resp.status_code == 403
    assert await _link_count(db_session) == 0


async def test_us1_create_requires_authentication(api_client: AsyncClient, folder_id):
    resp = await api_client.post(BASE, json={"folder_id": str(folder_id)}, auth=None)
    assert resp.status_code == 401


# US1 / Given a link is created, Then its token comes from a CSPRNG, only a keyed hash
# of the token is stored, and the raw token is returned once.
async def test_us1_only_keyed_hash_stored_and_token_returned_once(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    data = await _create(api_client, folder_id)
    token = data["token"]
    assert len(token) >= 43  # 32 CSPRNG bytes, URL-safe base64

    link = await _load(db_session, data["id"])
    assert link.token_hash == hash_token(token, SECRET)
    assert link.token_hash != token
    assert token not in {str(getattr(link, c.name)) for c in FolderShareLink.__table__.columns}

    listed = await api_client.get(BASE, params={"folder_id": str(folder_id)})
    assert listed.status_code == 200
    assert "token" not in listed.json()[0]
    assert token not in listed.text
    assert "token_hash" not in listed.text

    second = await _create(api_client, folder_id)
    assert second["token"] != token


# US1 / Given a valid, unexpired token, When anyone opens the link,
# Then they get a read-only view of F's contents.
async def test_us1_valid_token_gives_read_only_view_of_folder(
    api_client: AsyncClient, file_service: FakeFileService, owner_id, folder_id
):
    file_id = uuid.uuid4()
    updated = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    file_service.files[folder_id] = [
        FolderFile(id=file_id, name="plan.pdf", size=2048, mime_type="application/pdf",
                   updated_at=updated)
    ]
    created = await _create(api_client, folder_id)

    file_service.acting_users.clear()
    resp = await api_client.get(f"{BASE}/shared", params={"token": created["token"]}, auth=None)

    assert resp.status_code == 200, resp.text
    # Anonymous viewer: file-service is read on behalf of the link's creator (the owner).
    assert file_service.acting_users == [owner_id]
    body = resp.json()
    assert body["folder"] == {"id": str(folder_id), "name": "Q4 Reports"}
    assert body["files"] == [{
        "id": str(file_id), "name": "plan.pdf", "size": 2048,
        "mime_type": "application/pdf", "updated_at": "2026-11-01T12:00:00Z",
    }]
    assert body["expires_at"] == created["expires_at"]


async def test_us1_file_service_unavailable_returns_502(
    api_client: AsyncClient, file_service: FakeFileService, db_session: AsyncSession, folder_id
):
    file_service.unavailable = True
    resp = await api_client.post(BASE, json={"folder_id": str(folder_id)})
    assert resp.status_code == 502
    assert await _link_count(db_session) == 0


async def test_us1_missing_share_link_secret_returns_503(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, folder_id
):
    monkeypatch.delenv("SHARE_LINK_SECRET")
    resp = await api_client.post(BASE, json={"folder_id": str(folder_id)})
    assert resp.status_code == 503
    assert await _link_count(db_session) == 0


# --- Owner listing ------------------------------------------------------------------


# GET ?folder_id is owner only, newest first, and reports active|expired|revoked.
async def test_list_links_shows_status_and_is_owner_only(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    expired = await _create(api_client, folder_id)
    await _age_link(db_session, expired["id"], created_ago=10 * DAY, lifetime=DAY)
    revoked = await _create(api_client, folder_id)
    assert (await api_client.delete(f"{BASE}/{revoked['id']}")).status_code == 204
    active = await _create(api_client, folder_id)

    resp = await api_client.get(BASE, params={"folder_id": str(folder_id)})
    assert resp.status_code == 200
    by_id = {item["id"]: item for item in resp.json()}
    assert by_id[active["id"]]["status"] == "active"
    assert by_id[expired["id"]]["status"] == "expired"
    assert by_id[revoked["id"]]["status"] == "revoked"
    assert by_id[revoked["id"]]["revoked_at"] is not None
    assert set(by_id[active["id"]]) == {
        "id", "folder_id", "created_by", "created_at", "expires_at", "revoked_at", "status"
    }
    assert resp.json()[-1]["id"] == expired["id"]  # oldest last

    other = await api_client.get(
        BASE, params={"folder_id": str(folder_id)}, auth=bearer_auth(uuid.uuid4())
    )
    assert other.status_code == 403


# --- US3: Per-link override ---------------------------------------------------------


# US3 / Given I create a link, When I choose an expiry between 1 and 90 days
# (inside the workspace bounds), Then expires_at is set to that value.
@pytest.mark.parametrize("days", [1, 7, 90])
async def test_us3_create_with_override_inside_bounds(api_client: AsyncClient, folder_id, days):
    data = await _create(api_client, folder_id, expires_in_days=days)
    assert _ts(data["expires_at"]) - _ts(data["created_at"]) == timedelta(days=days)


# US3 / Given I choose a value outside the bounds, or "never", Then I get 422.
@pytest.mark.parametrize("value", [0, -1, 91, 365, "never", "", 7.5])
async def test_us3_create_outside_bounds_or_never_returns_422(
    api_client: AsyncClient, db_session: AsyncSession, folder_id, value
):
    resp = await api_client.post(BASE, json={"folder_id": str(folder_id), "expires_in_days": value})
    assert resp.status_code == 422
    assert await _link_count(db_session) == 0


# US3 / ... inside the workspace bounds: a narrower workspace policy is enforced too.
async def test_us3_create_outside_workspace_bounds_returns_422(
    api_client: AsyncClient, policy_client: FakePolicyClient, db_session: AsyncSession, folder_id
):
    policy_client.policy = SharingPolicy(default_expiry_days=7, min_expiry_days=3,
                                         max_expiry_days=10)
    for days in (2, 11):
        resp = await api_client.post(
            BASE, json={"folder_id": str(folder_id), "expires_in_days": days}
        )
        assert resp.status_code == 422
        assert "between 3 and 10" in resp.json()["detail"]
    assert await _link_count(db_session) == 0
    await _create(api_client, folder_id, expires_in_days=10)


# US3 / Given I edit a link, When I choose an expiry between 1 and 90 days,
# Then expires_at is set to that value (counted from the link's creation).
async def test_us3_edit_expiry_inside_bounds(api_client: AsyncClient, folder_id, events):
    created = await _create(api_client, folder_id)
    resp = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert _ts(body["expires_at"]) - _ts(created["created_at"]) == timedelta(days=5)
    assert events[-1][0] is ShareLinkEventType.EXPIRY_UPDATED
    assert events[-1][3] == {"expires_at": _ts(created["expires_at"]).isoformat()}


# US3 / Given I choose a value outside the bounds, or "never", Then I get 422 (edit).
@pytest.mark.parametrize("value", [0, 91, "never", None])
async def test_us3_edit_outside_bounds_returns_422(
    api_client: AsyncClient, db_session: AsyncSession, folder_id, value
):
    created = await _create(api_client, folder_id)
    resp = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": value})
    assert resp.status_code == 422
    link = await _load(db_session, created["id"])
    assert link.expires_at.replace(tzinfo=UTC) == _ts(created["expires_at"])


async def test_us3_edit_outside_workspace_bounds_returns_422(
    api_client: AsyncClient, policy_client: FakePolicyClient, folder_id
):
    created = await _create(api_client, folder_id)
    policy_client.policy = SharingPolicy(default_expiry_days=7, min_expiry_days=3,
                                         max_expiry_days=10)
    resp = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 30})
    assert resp.status_code == 422


# US3 / Given a link has expired, When I try to change its expiry, Then I get 409.
async def test_us3_edit_expired_link_returns_409(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    created = await _create(api_client, folder_id)
    await _age_link(db_session, created["id"], created_ago=3 * DAY, lifetime=DAY)
    resp = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 30})
    assert resp.status_code == 409
    link = await _load(db_session, created["id"])
    assert link.expires_at.replace(tzinfo=UTC) < datetime.now(UTC)


# US3 / editing a revoked link is also rejected with 409 (contract).
async def test_us3_edit_revoked_link_returns_409(api_client: AsyncClient, folder_id):
    created = await _create(api_client, folder_id)
    assert (await api_client.delete(f"{BASE}/{created['id']}")).status_code == 204
    resp = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 30})
    assert resp.status_code == 409


async def test_us3_edit_by_non_owner_returns_403_and_unknown_link_404(
    api_client: AsyncClient, folder_id
):
    created = await _create(api_client, folder_id)
    resp = await api_client.patch(
        f"{BASE}/{created['id']}", json={"expires_in_days": 5}, auth=bearer_auth(uuid.uuid4())
    )
    assert resp.status_code == 403
    resp = await api_client.patch(f"{BASE}/{uuid.uuid4()}", json={"expires_in_days": 5})
    assert resp.status_code == 404


# US3 / Given I revoke a link, Then it stops working at once and its record is kept
# for the audit trail.
async def test_us3_revoke_stops_link_at_once_and_keeps_record(
    api_client: AsyncClient, db_session: AsyncSession, folder_id, events
):
    created = await _create(api_client, folder_id)
    opened = await api_client.get(f"{BASE}/shared", params={"token": created["token"]}, auth=None)
    assert opened.status_code == 200

    resp = await api_client.delete(f"{BASE}/{created['id']}")
    assert resp.status_code == 204

    opened = await api_client.get(f"{BASE}/shared", params={"token": created["token"]}, auth=None)
    assert opened.status_code == 410
    assert opened.json() == {"detail": "link_revoked"}
    link = await _load(db_session, created["id"])
    assert link.revoked_at is not None
    assert await _link_count(db_session) == 1
    assert events[-1][0] is ShareLinkEventType.REVOKED


async def test_us3_revoke_twice_keeps_first_revocation(
    api_client: AsyncClient, db_session: AsyncSession, folder_id, events
):
    created = await _create(api_client, folder_id)
    assert (await api_client.delete(f"{BASE}/{created['id']}")).status_code == 204
    first = (await _load(db_session, created["id"])).revoked_at
    assert (await api_client.delete(f"{BASE}/{created['id']}")).status_code == 204
    assert (await _load(db_session, created["id"])).revoked_at == first
    assert [e[0] for e in events].count(ShareLinkEventType.REVOKED) == 1


async def test_us3_revoke_by_non_owner_returns_403(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    created = await _create(api_client, folder_id)
    resp = await api_client.delete(f"{BASE}/{created['id']}", auth=bearer_auth(uuid.uuid4()))
    assert resp.status_code == 403
    assert (await _load(db_session, created["id"])).revoked_at is None
    assert (await api_client.delete(f"{BASE}/{uuid.uuid4()}")).status_code == 404


# --- US4: Expired link --------------------------------------------------------------


# US4 / Given a link's expires_at is in the past, When anyone opens it,
# Then the API returns HTTP 410 Gone.
async def test_us4_expired_link_returns_410(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    created = await _create(api_client, folder_id)
    await _age_link(db_session, created["id"], created_ago=31 * DAY, lifetime=30 * DAY)
    resp = await api_client.get(f"{BASE}/shared", params={"token": created["token"]}, auth=None)
    assert resp.status_code == 410
    assert resp.json() == {"detail": "link_expired"}


# US4 / Given a link has been revoked, When anyone opens it, Then the API returns 410.
async def test_us4_revoked_link_returns_410_even_if_also_expired(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    created = await _create(api_client, folder_id)
    assert (await api_client.delete(f"{BASE}/{created['id']}")).status_code == 204
    resp = await api_client.get(f"{BASE}/shared", params={"token": created["token"]}, auth=None)
    assert resp.status_code == 410
    assert resp.json() == {"detail": "link_revoked"}


# US4 / Given an unknown or tampered token, Then the API returns 404, not 410.
async def test_us4_unknown_or_tampered_token_returns_404(api_client: AsyncClient, folder_id):
    created = await _create(api_client, folder_id)
    token = created["token"]
    tampered = ("A" if token[0] != "A" else "B") + token[1:]
    for candidate in ("not-a-real-token", tampered, token + "x"):
        resp = await api_client.get(f"{BASE}/shared", params={"token": candidate}, auth=None)
        assert resp.status_code == 404, candidate


# US4 / a link whose folder was deleted in file-service is treated as unknown.
async def test_us4_link_to_deleted_folder_returns_404(
    api_client: AsyncClient, file_service: FakeFileService, folder_id
):
    created = await _create(api_client, folder_id)
    del file_service.folders[folder_id]
    resp = await api_client.get(f"{BASE}/shared", params={"token": created["token"]}, auth=None)
    assert resp.status_code == 404


# --- Expiry is never silently extended ----------------------------------------------


# Given a link has expired, When it is opened or listed, Then expires_at is unchanged.
async def test_expiry_not_extended_by_opening_or_listing(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    created = await _create(api_client, folder_id)
    await _age_link(db_session, created["id"], created_ago=2 * DAY, lifetime=DAY)
    before = (await _load(db_session, created["id"])).expires_at

    await api_client.get(f"{BASE}/shared", params={"token": created["token"]}, auth=None)
    await api_client.get(BASE, params={"folder_id": str(folder_id)})

    assert (await _load(db_session, created["id"])).expires_at == before


# Given the workspace default changes, Then existing links keep their expires_at.
async def test_expiry_not_extended_when_policy_changes(
    api_client: AsyncClient, policy_client: FakePolicyClient, db_session: AsyncSession, folder_id
):
    created = await _create(api_client, folder_id)
    policy_client.policy = SharingPolicy(default_expiry_days=90, min_expiry_days=1,
                                         max_expiry_days=90)
    newer = await _create(api_client, folder_id)

    assert (await _load(db_session, created["id"])).expires_at.replace(tzinfo=UTC) == _ts(
        created["expires_at"]
    )
    assert _ts(newer["expires_at"]) - _ts(newer["created_at"]) == timedelta(days=90)


# Given I edit a link, Then its lifetime is counted from created_at, so repeated edits
# cannot keep it alive past the maximum (no "never expire").
async def test_expiry_edit_is_anchored_to_creation(
    api_client: AsyncClient, db_session: AsyncSession, folder_id
):
    created = await _create(api_client, folder_id)
    await _age_link(db_session, created["id"], created_ago=89 * DAY, lifetime=90 * DAY)
    link = await _load(db_session, created["id"])
    created_at = link.created_at.replace(tzinfo=UTC)

    resp = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 90})
    assert resp.status_code == 200
    assert _ts(resp.json()["expires_at"]) == created_at + timedelta(days=90)

    resp = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 30})
    assert resp.status_code == 422  # would land in the past
    assert (await _load(db_session, created["id"])).expires_at.replace(
        tzinfo=UTC
    ) == created_at + timedelta(days=90)


# --- Audit hook (OTW-69) ------------------------------------------------------------


async def test_lifecycle_calls_audit_hook(
    api_client: AsyncClient, owner_id, folder_id, events
):
    created = await _create(api_client, folder_id)
    assert events[0][0] is ShareLinkEventType.CREATED
    assert events[0][1] == uuid.UUID(created["id"])
    assert events[0][2] == owner_id
    assert events[0][3] is None
    assert events[0][4] == {"expires_at": _ts(created["expires_at"]).isoformat()}

    resp = await api_client.post(BASE, json={"folder_id": str(folder_id)},
                                 auth=bearer_auth(uuid.uuid4()))
    assert resp.status_code == 403
    assert len(events) == 1  # rejected requests emit nothing
