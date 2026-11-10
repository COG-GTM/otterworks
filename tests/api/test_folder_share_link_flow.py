"""Expiring folder share links (OTW-41), black-box through the API gateway.

Each test names the OTW-41 Requirements Document scenario it covers (Given/When/Then in the
docstring). Two setup steps have no public API and go straight to the services' Postgres
database through the ``otterworks_db`` fixture, so no test-only bypass ships in any service:

* granting the workspace-owner role (auth-service only ever registers ``USER``), and
* back-dating a link's ``expires_at`` so expiry can be observed without waiting a day
  (PATCH is bounded to >= 1 day by design).

Tests needing either skip with a clear reason when no database is configured.
"""

import csv
import io
import json
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest


pytestmark = pytest.mark.api_flow

SHARE_LINKS = "/api/v1/share-links"
SHARE_POLICY = "/api/v1/workspace/share-policy"
BUILTIN_DEFAULT_DAYS = 30
BUILTIN_MAX_DAYS = 90
WORKSPACE_OWNER_ROLE = "OWNER"
# Clock skew between the test runner and document-service, plus request latency.
TIME_TOLERANCE = timedelta(minutes=2)
URLSAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
MIN_TOKEN_CHARS = 22  # 22 urlsafe base64 chars carry >= 128 bits
OMIT = object()


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def assert_close(actual: datetime, expected: datetime) -> None:
    assert abs(actual - expected) <= TIME_TOLERANCE, f"{actual} is not within {TIME_TOLERANCE} of {expected}"


def get_policy(api_client, user) -> dict[str, Any]:
    response = api_client.client.get(SHARE_POLICY, headers=user.auth_headers)
    api_client.assert_gateway_route_available(response, SHARE_POLICY)
    assert response.status_code == 200, response.text
    return response.json()


def put_policy(api_client, user, body: dict[str, Any]) -> httpx.Response:
    return api_client.client.put(SHARE_POLICY, headers=user.auth_headers, json=body)


def create_link(api_client, user, folder_id: str, expires_in_days: Any = OMIT) -> httpx.Response:
    body: dict[str, Any] = {"resource_type": "folder", "resource_id": folder_id}
    if expires_in_days is not OMIT:
        body["expires_in_days"] = expires_in_days
    response = api_client.client.post(SHARE_LINKS, headers=user.auth_headers, json=body)
    api_client.assert_gateway_route_available(response, SHARE_LINKS)
    return response


def create_link_ok(api_client, user, folder_id: str, expires_in_days: Any = OMIT) -> dict[str, Any]:
    response = create_link(api_client, user, folder_id, expires_in_days)
    assert response.status_code == 201, response.text
    return response.json()


def list_links(api_client, user, folder_id: str) -> list[dict[str, Any]]:
    response = api_client.client.get(
        SHARE_LINKS, headers=user.auth_headers, params={"resource_id": folder_id}
    )
    assert response.status_code == 200, response.text
    return response.json()


def resolve(api_client, token: str, **kwargs: Any) -> httpx.Response:
    """Open a link the way a recipient does: no Authorization header."""
    return api_client.client.get(f"{SHARE_LINKS}/resolve/{token}", **kwargs)


def expire_link_in_db(db, link_id: str) -> datetime:
    """Back-date expires_at (test setup only; the API never shortens a link below 1 day)."""
    row = db.execute(
        "UPDATE share_links SET expires_at = now() - interval '5 minutes' WHERE id = %s RETURNING expires_at",
        (link_id,),
    ).fetchone()
    assert row is not None, f"share link {link_id} not found in share_links"
    return row[0]


@pytest.fixture
def owner(api_client):
    return api_client.register_user("share-link-owner")


@pytest.fixture
def workspace_owner(api_client, otterworks_db):
    """A real registered user granted the workspace-owner role, logged in again for a fresh JWT."""
    user = api_client.register_user("share-ws-owner")
    otterworks_db.execute(
        "INSERT INTO user_roles (user_id, role) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (user.id, WORKSPACE_OWNER_ROLE),
    )
    promoted = api_client.login_as(user)
    return promoted


@pytest.fixture
def new_workspace_policy(api_client, otterworks_db, owner) -> Iterator[str]:
    """Give the suite's workspace no saved policy (a "new workspace"), restoring it afterwards.

    Registered users carry no ``workspace_id`` claim yet (OTW-42), so they all resolve to the
    default workspace; its saved row, if any, is put back exactly as it was.
    """
    workspace_id = get_policy(api_client, owner)["workspace_id"]
    saved = otterworks_db.execute(
        "SELECT default_days, max_days, updated_by, updated_at "
        "FROM workspace_share_policy WHERE workspace_id = %s",
        (workspace_id,),
    ).fetchone()
    otterworks_db.execute("DELETE FROM workspace_share_policy WHERE workspace_id = %s", (workspace_id,))
    try:
        yield workspace_id
    finally:
        otterworks_db.execute("DELETE FROM workspace_share_policy WHERE workspace_id = %s", (workspace_id,))
        if saved is not None:
            otterworks_db.execute(
                "INSERT INTO workspace_share_policy "
                "(workspace_id, default_days, max_days, updated_by, updated_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (workspace_id, *saved),
            )


# --- Story 1: Workspace default -------------------------------------------------------------


def test_scenario_new_workspace_policy_defaults_to_30_and_90_days(api_client, owner, new_workspace_policy):
    """Scenario: Given a new workspace, When its sharing policy is read,
    Then the default expiry is 30 days and the maximum is 90 days."""
    policy = get_policy(api_client, owner)

    assert policy["workspace_id"] == new_workspace_policy
    assert policy["default_days"] == BUILTIN_DEFAULT_DAYS
    assert policy["max_days"] == BUILTIN_MAX_DAYS
    assert policy["updated_by"] is None


def test_scenario_workspace_owner_sets_valid_default_and_it_is_used_for_new_links(
    api_client, workspace_owner, new_workspace_policy
):
    """Scenario: Given a workspace owner, When they set a default between 1 and 90 days
    (no higher than the maximum), Then it is saved and used for new folder links."""
    response = put_policy(api_client, workspace_owner, {"default_days": 14, "max_days": 60})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert (saved["default_days"], saved["max_days"]) == (14, 60)
    assert saved["workspace_id"] == new_workspace_policy
    assert saved["updated_by"] == workspace_owner.id

    reread = get_policy(api_client, workspace_owner)
    assert (reread["default_days"], reread["max_days"]) == (14, 60)

    folder = api_client.create_folder(workspace_owner, f"Policy Folder {api_client.run_id}")
    link = create_link_ok(api_client, workspace_owner, folder["id"])
    assert_close(parse_ts(link["expires_at"]), parse_ts(link["created_at"]) + timedelta(days=14))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"default_days": 0, "max_days": 90}, id="default-below-1"),
        pytest.param({"default_days": 91, "max_days": 90}, id="default-above-90"),
        pytest.param({"default_days": 30, "max_days": 91}, id="max-above-90"),
        pytest.param({"default_days": 60, "max_days": 30}, id="default-above-max"),
        pytest.param({"default_days": None, "max_days": 90}, id="default-never-null"),
        pytest.param({"default_days": 30, "max_days": None}, id="max-never-null"),
        pytest.param({"default_days": "never", "max_days": 90}, id="default-never-string"),
    ],
)
def test_scenario_workspace_owner_out_of_range_policy_rejected_with_422(
    api_client, workspace_owner, new_workspace_policy, body
):
    """Scenario: Given a workspace owner, When they try a default above 90 days, below 1 day,
    or "never", Then the request is rejected with 422 (and the policy is unchanged)."""
    response = put_policy(api_client, workspace_owner, body)

    assert response.status_code == 422, response.text
    api_client.assert_json_error(response)
    policy = get_policy(api_client, workspace_owner)
    assert (policy["default_days"], policy["max_days"]) == (BUILTIN_DEFAULT_DAYS, BUILTIN_MAX_DAYS)


def test_scenario_non_owner_policy_change_rejected_with_403(api_client, owner):
    """Scenario: Given a user who is not a workspace owner, When they try to change the policy,
    Then the request is rejected with 403."""
    before = get_policy(api_client, owner)

    response = put_policy(api_client, owner, {"default_days": 7, "max_days": 30})

    assert response.status_code == 403, response.text
    api_client.assert_json_error(response)
    after = get_policy(api_client, owner)
    assert (after["default_days"], after["max_days"], after["updated_at"]) == (
        before["default_days"],
        before["max_days"],
        before["updated_at"],
    )


def test_scenario_policy_change_does_not_alter_existing_links(
    api_client, workspace_owner, new_workspace_policy
):
    """Scenario: Given links that already exist, When the workspace default changes,
    Then their expiry does not change (no retroactive change)."""
    folder = api_client.create_folder(workspace_owner, f"Retro Folder {api_client.run_id}")
    default_link = create_link_ok(api_client, workspace_owner, folder["id"])
    long_link = create_link_ok(api_client, workspace_owner, folder["id"], 60)

    response = put_policy(api_client, workspace_owner, {"default_days": 7, "max_days": 30})
    assert response.status_code == 200, response.text

    current = {link["id"]: link for link in list_links(api_client, workspace_owner, folder["id"])}
    assert parse_ts(current[default_link["id"]]["expires_at"]) == parse_ts(default_link["expires_at"])
    # Above the new 30-day maximum, but left as it was.
    assert parse_ts(current[long_link["id"]]["expires_at"]) == parse_ts(long_link["expires_at"])

    new_link = create_link_ok(api_client, workspace_owner, folder["id"])
    assert_close(parse_ts(new_link["expires_at"]), parse_ts(new_link["created_at"]) + timedelta(days=7))
    assert create_link(api_client, workspace_owner, folder["id"], 60).status_code == 422


# --- Story 2: Create a folder link ----------------------------------------------------------


def test_scenario_create_folder_link_without_expiry_uses_workspace_default(api_client, owner):
    """Scenario: Given a folder the user owns, When they create a link without choosing an
    expiry, Then expires_at = now + the workspace default, and the link record is returned."""
    default_days = get_policy(api_client, owner)["default_days"]
    folder = api_client.create_folder(owner, f"Default Expiry Folder {api_client.run_id}")

    before = datetime.now(UTC)
    link = create_link_ok(api_client, owner, folder["id"])

    assert {"id", "token", "url", "resource_type", "resource_id", "expires_at", "created_at"} <= set(link)
    assert link["resource_type"] == "folder"
    assert link["resource_id"] == folder["id"]
    assert link["url"].endswith(f"/s/{link['token']}")
    assert_close(parse_ts(link["created_at"]), before)
    assert_close(parse_ts(link["expires_at"]), before + timedelta(days=default_days))
    assert [item["id"] for item in list_links(api_client, owner, folder["id"])] == [link["id"]]


@pytest.mark.parametrize("pick", ["min", "max"])
def test_scenario_create_folder_link_with_expiry_override_within_bounds_is_saved(api_client, owner, pick):
    """Scenario: Given a folder the user owns, When they choose an expiry from 1 day to the
    workspace maximum, Then that expiry is saved on the link."""
    days = 1 if pick == "min" else get_policy(api_client, owner)["max_days"]
    folder = api_client.create_folder(owner, f"Override Folder {api_client.run_id}")

    before = datetime.now(UTC)
    link = create_link_ok(api_client, owner, folder["id"], days)

    assert_close(parse_ts(link["expires_at"]), before + timedelta(days=days))
    saved = list_links(api_client, owner, folder["id"])
    assert [(item["id"], parse_ts(item["expires_at"])) for item in saved] == [
        (link["id"], parse_ts(link["expires_at"]))
    ]


@pytest.mark.parametrize("override", ["above-max", "zero", "null"])
def test_scenario_create_folder_link_above_max_rejected_with_422_and_no_link_created(
    api_client, owner, override
):
    """Scenario: Given an override above the workspace maximum (or below 1 day, or "never"),
    When the link is created, Then the request is rejected with 422 and no link is created."""
    max_days = get_policy(api_client, owner)["max_days"]
    days = {"above-max": max_days + 1, "zero": 0, "null": None}[override]
    folder = api_client.create_folder(owner, f"Rejected Folder {api_client.run_id}")

    response = create_link(api_client, owner, folder["id"], days)

    assert response.status_code == 422, response.text
    api_client.assert_json_error(response)
    assert list_links(api_client, owner, folder["id"]) == []


def test_scenario_edit_folder_link_above_max_rejected_with_422(api_client, owner):
    """Scenario: Given an override above the workspace maximum, When the link is edited,
    Then the request is rejected with 422 and the link keeps its expiry."""
    max_days = get_policy(api_client, owner)["max_days"]
    folder = api_client.create_folder(owner, f"Edit Folder {api_client.run_id}")
    link = create_link_ok(api_client, owner, folder["id"], 1)

    rejected = api_client.client.patch(
        f"{SHARE_LINKS}/{link['id']}", headers=owner.auth_headers, json={"expires_in_days": max_days + 1}
    )
    assert rejected.status_code == 422, rejected.text

    before = datetime.now(UTC)
    edited = api_client.client.patch(
        f"{SHARE_LINKS}/{link['id']}", headers=owner.auth_headers, json={"expires_in_days": 2}
    )
    assert edited.status_code == 200, edited.text
    assert_close(parse_ts(edited.json()["expires_at"]), before + timedelta(days=2))


def test_scenario_share_token_is_opaque_high_entropy_and_unique(api_client, owner):
    """Scenario: Given a link is created, Then the token comes from a CSPRNG (at least 128 bits),
    never an unkeyed hash: it is opaque, long enough, and unique across links."""
    folder = api_client.create_folder(owner, f"Token Folder {api_client.run_id}")
    links = [create_link_ok(api_client, owner, folder["id"]) for _ in range(5)]
    tokens = [link["token"] for link in links]

    assert len(set(tokens)) == len(tokens)
    for link in links:
        token = link["token"]
        assert URLSAFE_TOKEN.match(token), token
        assert len(token) >= MIN_TOKEN_CHARS, f"{len(token)} chars carry fewer than 128 bits"
        # The legacy document token is a truncated hex MD5; a CSPRNG token is not hex-only.
        assert not re.fullmatch(r"[0-9a-f]+", token), token
        for identifier in (folder["id"], link["id"], owner.id):
            assert identifier not in token
            assert identifier.replace("-", "") not in token


def test_scenario_valid_link_lists_folder_read_only_and_nothing_can_be_written(api_client, owner):
    """Scenario: Given a valid link, When it is opened, Then the folder's contents are listed
    read-only and nothing can be written."""
    folder = api_client.create_folder(owner, f"Shared Folder {api_client.run_id}")
    uploaded = [
        api_client.upload_file(owner, folder["id"], f"shared-{index}.txt", f"body {index}".encode())
        for index in range(2)
    ]
    link = create_link_ok(api_client, owner, folder["id"])
    token = link["token"]

    response = resolve(api_client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resource_type"] == "folder"
    assert body["folder"]["id"] == folder["id"]
    assert parse_ts(body["expires_at"]) == parse_ts(link["expires_at"])
    assert sorted((f["id"], f["name"]) for f in body["files"]) == sorted(
        (f["id"], f["name"]) for f in uploaded
    )
    for leaked in ("owner_id", "s3_key"):
        assert leaked not in body["folder"]
        assert all(leaked not in f for f in body["files"])

    resolve_url = f"{SHARE_LINKS}/resolve/{token}"
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        attempt = api_client.client.request(method, resolve_url, json={"name": "renamed"})
        assert attempt.status_code in {401, 403, 404, 405}, f"{method} {resolve_url}: {attempt.text}"

    token_as_credential = {"Authorization": f"Bearer {token}"}
    writes = [
        api_client.client.post(
            "/api/v1/files/upload",
            headers=token_as_credential,
            files={"file": ("intruder.txt", b"intruder", "text/plain")},
            data={"folder_id": folder["id"]},
        ),
        api_client.client.delete(f"/api/v1/files/{uploaded[0]['id']}", headers=token_as_credential),
        api_client.client.delete(f"/api/v1/folders/{folder['id']}", headers=token_as_credential),
        api_client.client.patch(
            f"{SHARE_LINKS}/{link['id']}", headers=token_as_credential, json={"expires_in_days": 1}
        ),
    ]
    for attempt in writes:
        assert attempt.status_code in {401, 403}, (
            f"{attempt.request.method} {attempt.request.url}: {attempt.text}"
        )

    again = resolve(api_client, token)
    assert again.status_code == 200, again.text
    assert sorted(f["id"] for f in again.json()["files"]) == sorted(f["id"] for f in uploaded)
    assert parse_ts(again.json()["expires_at"]) == parse_ts(link["expires_at"])


def test_scenario_valid_link_lists_only_folder_owners_files_not_files_moved_in_by_others(api_client, owner):
    """Scenario: Given a valid link to a folder, When another user moves their own file into
    that folder and the link is opened, Then only the folder owner's files are listed."""
    folder = api_client.create_folder(owner, f"Owner Folder {api_client.run_id}")
    owners_file = api_client.upload_file(owner, folder["id"], "owners.txt", b"owner's file")
    link = create_link_ok(api_client, owner, folder["id"])

    other = api_client.register_user("share-link-other")
    other_folder = api_client.create_folder(other, f"Other Folder {api_client.run_id}")
    others_file = api_client.upload_file(other, other_folder["id"], "others.txt", b"not shared")
    move = api_client.client.put(
        f"/api/v1/files/{others_file['id']}/move",
        headers=other.auth_headers,
        json={"folder_id": folder["id"]},
    )
    if move.status_code in {403, 404, 422}:
        pytest.skip(f"file-service refuses moves into another user's folder ({move.status_code})")
    assert move.status_code == 200, move.text
    assert move.json()["folder_id"] == folder["id"]

    response = resolve(api_client, link["token"])
    assert response.status_code == 200, response.text
    listed = [f["id"] for f in response.json()["files"]]
    assert others_file["id"] not in listed
    assert listed == [owners_file["id"]]


# --- Story 3: Expired links -----------------------------------------------------------------


def test_scenario_expired_link_returns_410_and_expiry_is_never_extended(api_client, owner, otterworks_db):
    """Scenario: Given a link whose expires_at has passed, When it is opened, Then the response
    is HTTP 410; and Given an expired link, When it is accessed again or edited, Then the
    expiry is never extended automatically."""
    folder = api_client.create_folder(owner, f"Expiring Folder {api_client.run_id}")
    link = create_link_ok(api_client, owner, folder["id"], 1)
    expired_expires_at = expire_link_in_db(otterworks_db, link["id"])

    first = resolve(api_client, link["token"])
    assert first.status_code == 410, first.text
    body = first.json()
    assert body["error"] == "link_expired"
    assert body["expired_at"] is not None
    assert_close(parse_ts(body["expired_at"]), datetime.now(UTC))
    assert "no-store" in first.headers.get("cache-control", "")

    second = resolve(api_client, link["token"])
    assert second.status_code == 410, second.text
    assert second.json() == body, "expired_at must be recorded once and not move"

    edit = api_client.client.patch(
        f"{SHARE_LINKS}/{link['id']}", headers=owner.auth_headers, json={"expires_in_days": 5}
    )
    assert edit.status_code == 410, edit.text
    assert resolve(api_client, link["token"]).status_code == 410

    [stored] = list_links(api_client, owner, folder["id"])
    assert parse_ts(stored["expires_at"]) == expired_expires_at.astimezone(UTC)
    assert parse_ts(stored["expired_at"]) == parse_ts(body["expired_at"])


def test_scenario_pre_existing_document_share_token_still_works_with_no_expiry(api_client):
    """Scenario: Given a document share token that existed before release, When it is opened,
    Then it still works with no expiry."""
    doc_owner = api_client.register_user("legacy-share-owner")
    viewer = api_client.register_user("legacy-share-viewer")
    document = api_client.create_document(doc_owner, f"Legacy Share {api_client.run_id}", "legacy body")

    minted = api_client.client.post(
        f"/api/v1/documents/{document['id']}/share", headers=doc_owner.auth_headers
    )
    assert minted.status_code == 200, minted.text
    assert set(minted.json()) == {"document_id", "token"}, "legacy tokens carry no expiry"
    token = minted.json()["token"]

    for _ in range(2):
        shared = api_client.client.get(
            "/api/v1/documents/shared",
            headers=viewer.auth_headers,
            params={"document_id": document["id"], "token": token},
        )
        assert shared.status_code == 200, shared.text
        assert shared.json()["id"] == document["id"]

    tampered = api_client.client.get(
        "/api/v1/documents/shared",
        headers=viewer.auth_headers,
        params={"document_id": document["id"], "token": f"{token}x"},
    )
    assert tampered.status_code == 403, tampered.text
    # Document tokens are not folder share links and are not looked up there.
    assert resolve(api_client, token).status_code == 404


# --- Story 4: Audit and export --------------------------------------------------------------

AUDIT_EVENTS = "/api/v1/audit/events"
CSV_AUDIT_COLUMNS = ("WorkspaceId", "OldValue", "NewValue")


def require_audit_eventing(api_client, user) -> None:
    flag = os.getenv("OTTERWORKS_API_SNS_EVENTING", "").strip().lower()
    if flag in {"0", "false", "off", "disabled", "no"}:
        pytest.skip(
            f"SNS/SQS eventing is disabled in this environment (OTTERWORKS_API_SNS_EVENTING={flag}); "
            "document-service audit events cannot reach audit-service"
        )
    try:
        probe = api_client.client.get(AUDIT_EVENTS, headers=user.auth_headers, params={"size": 1})
    except httpx.HTTPError as exc:
        pytest.skip(f"audit-service is not reachable through the gateway: {exc}")
    if probe.status_code in {502, 503, 504}:
        pytest.skip(f"audit-service is not reachable through the gateway (HTTP {probe.status_code})")
    assert probe.status_code == 200, probe.text


def audit_poll_timeout() -> float:
    # audit-service long-polls SQS for up to 20s per receive.
    return max(float(os.getenv("OTTERWORKS_API_POLL_TIMEOUT", "30")), 60.0)


def wait_for_audit_event(api_client, user, **params: str) -> dict[str, Any]:
    def probe() -> list[dict[str, Any]]:
        response = api_client.client.get(
            AUDIT_EVENTS, headers=user.auth_headers, params={**params, "size": 100}
        )
        assert response.status_code == 200, response.text
        return response.json()["events"]

    events = api_client.poll_until(
        probe,
        predicate=lambda found: len(found) >= 1,
        timeout_seconds=audit_poll_timeout(),
        description=(
            f"audit event {params} (if SNS/SQS eventing is off here, set OTTERWORKS_API_SNS_EVENTING=0)"
        ),
    )
    assert len(events) == 1, events
    return events[0]


def run_share_link_lifecycle(api_client, workspace_owner, otterworks_db) -> dict[str, Any]:
    """Create, edit and expire a link, then change the policy; return what each event should say."""
    workspace_id = get_policy(api_client, workspace_owner)["workspace_id"]
    folder = api_client.create_folder(workspace_owner, f"Audit Folder {api_client.run_id}")
    started_at = datetime.now(UTC) - timedelta(minutes=1)

    created = create_link_ok(api_client, workspace_owner, folder["id"])
    patched = api_client.client.patch(
        f"{SHARE_LINKS}/{created['id']}", headers=workspace_owner.auth_headers, json={"expires_in_days": 2}
    )
    assert patched.status_code == 200, patched.text
    patched_expires_at = patched.json()["expires_at"]

    expired_expires_at = expire_link_in_db(otterworks_db, created["id"]).astimezone(UTC)
    gone = resolve(api_client, created["token"])
    assert gone.status_code == 410, gone.text

    policy_response = put_policy(api_client, workspace_owner, {"default_days": 10, "max_days": 45})
    assert policy_response.status_code == 200, policy_response.text

    return {
        "workspace_id": workspace_id,
        "folder_id": folder["id"],
        "link_id": created["id"],
        "started_at": started_at,
        "created_expires_at": parse_ts(created["expires_at"]),
        "patched_expires_at": parse_ts(patched_expires_at),
        "expired_expires_at": expired_expires_at,
        "expired_at": parse_ts(gone.json()["expired_at"]),
    }


def json_value(raw: str | None) -> Any:
    return json.loads(raw) if raw else None


def assert_ts_field(value: dict[str, Any] | None, key: str, expected: datetime) -> None:
    assert value is not None and key in value, value
    assert parse_ts(value[key]) == expected


def test_scenario_audit_event_recorded_for_link_create_change_expiry_and_policy_change(
    api_client, workspace_owner, otterworks_db, new_workspace_policy
):
    """Scenario: Given a link is created, its expiry is changed, or it expires, Then an audit
    event is sent to audit-service with actor, workspace, resource, old value, new value and
    timestamp; and Given the workspace policy changes, Then an audit event records the old and
    new default and maximum."""
    require_audit_eventing(api_client, workspace_owner)
    flow = run_share_link_lifecycle(api_client, workspace_owner, otterworks_db)

    created = wait_for_audit_event(
        api_client, workspace_owner, action="share_link_created", resource=flow["folder_id"]
    )
    changed = wait_for_audit_event(
        api_client, workspace_owner, action="share_link_expiry_changed", resource=flow["folder_id"]
    )
    expired = wait_for_audit_event(
        api_client, workspace_owner, action="share_link_expired", resource=flow["folder_id"]
    )
    policy = wait_for_audit_event(
        api_client, workspace_owner, action="workspace_share_policy_changed", user_id=workspace_owner.id
    )

    for event in (created, changed, expired):
        assert event["resourceType"] == "folder"
        assert event["resourceId"] == flow["folder_id"]
        assert event["workspaceId"] == flow["workspace_id"]
        assert (event.get("details") or {}).get("share_link_id") == flow["link_id"]
        assert parse_ts(event["timestamp"]) >= flow["started_at"]
    assert created["userId"] == workspace_owner.id
    assert changed["userId"] == workspace_owner.id
    assert expired["userId"] == "system"

    assert json_value(created["oldValue"]) is None
    assert_ts_field(json_value(created["newValue"]), "expires_at", flow["created_expires_at"])
    assert_ts_field(json_value(changed["oldValue"]), "expires_at", flow["created_expires_at"])
    assert_ts_field(json_value(changed["newValue"]), "expires_at", flow["patched_expires_at"])
    assert_ts_field(json_value(expired["oldValue"]), "expires_at", flow["expired_expires_at"])
    assert_ts_field(json_value(expired["newValue"]), "expired_at", flow["expired_at"])

    assert policy["resourceType"] == "workspace"
    assert policy["resourceId"] == flow["workspace_id"]
    assert policy["workspaceId"] == flow["workspace_id"]
    assert json_value(policy["oldValue"]) == {
        "default_days": BUILTIN_DEFAULT_DAYS,
        "max_days": BUILTIN_MAX_DAYS,
    }
    assert json_value(policy["newValue"]) == {"default_days": 10, "max_days": 45}


def test_scenario_audit_csv_export_includes_workspace_old_and_new_value_columns(
    api_client, workspace_owner, otterworks_db, new_workspace_policy, s3_endpoint
):
    """Scenario: Given a compliance reviewer, When they export audit history as CSV, Then the
    file includes WorkspaceId, OldValue and NewValue columns alongside the existing columns,
    with correct CSV escaping."""
    require_audit_eventing(api_client, workspace_owner)
    if not s3_endpoint:
        pytest.skip(
            "Set OTTERWORKS_API_S3_ENDPOINT to read audit CSV exports from S3 for a non-local gateway"
        )
    flow = run_share_link_lifecycle(api_client, workspace_owner, otterworks_db)
    for action in ("share_link_created", "share_link_expiry_changed", "share_link_expired"):
        wait_for_audit_event(api_client, workspace_owner, action=action, resource=flow["folder_id"])
    wait_for_audit_event(
        api_client, workspace_owner, action="workspace_share_policy_changed", user_id=workspace_owner.id
    )

    export = api_client.client.get(
        "/api/v1/audit/export",
        headers=workspace_owner.auth_headers,
        params={"format": "csv", "from": flow["started_at"].isoformat()},
    )
    assert export.status_code == 200, export.text
    download_url = export.json()["downloadUrl"]
    assert download_url.startswith("s3://"), download_url
    bucket_and_key = download_url.removeprefix("s3://")
    try:
        csv_response = httpx.get(f"{s3_endpoint}/{bucket_and_key}", timeout=10.0)
    except httpx.HTTPError as exc:
        pytest.skip(f"S3 endpoint {s3_endpoint} is not reachable to download the export: {exc}")
    assert csv_response.status_code == 200, csv_response.text

    reader = csv.DictReader(io.StringIO(csv_response.text))
    header = reader.fieldnames or []
    for column in ("Id", "Timestamp", "UserId", "Action", "ResourceType", "ResourceId", *CSV_AUDIT_COLUMNS):
        assert column in header, header
    assert header[-3:] == list(CSV_AUDIT_COLUMNS)
    rows = list(reader)

    by_action = {row["Action"]: row for row in rows if row["ResourceId"] == flow["folder_id"]}
    assert {"share_link_created", "share_link_expiry_changed", "share_link_expired"} <= set(by_action)
    for row in by_action.values():
        assert row["WorkspaceId"] == flow["workspace_id"]
    assert by_action["share_link_created"]["OldValue"] == ""
    # JSON values contain quotes and commas; DictReader only round-trips them if escaped.
    assert_ts_field(
        json_value(by_action["share_link_created"]["NewValue"]), "expires_at", flow["created_expires_at"]
    )
    assert_ts_field(
        json_value(by_action["share_link_expiry_changed"]["OldValue"]),
        "expires_at",
        flow["created_expires_at"],
    )
    assert_ts_field(
        json_value(by_action["share_link_expiry_changed"]["NewValue"]),
        "expires_at",
        flow["patched_expires_at"],
    )
    assert_ts_field(json_value(by_action["share_link_expired"]["NewValue"]), "expired_at", flow["expired_at"])

    policy_rows = [
        row
        for row in rows
        if row["Action"] == "workspace_share_policy_changed" and row["UserId"] == workspace_owner.id
    ]
    assert len(policy_rows) == 1, policy_rows
    assert policy_rows[0]["WorkspaceId"] == flow["workspace_id"]
    assert json_value(policy_rows[0]["OldValue"]) == {
        "default_days": BUILTIN_DEFAULT_DAYS,
        "max_days": BUILTIN_MAX_DAYS,
    }
    assert json_value(policy_rows[0]["NewValue"]) == {"default_days": 10, "max_days": 45}
