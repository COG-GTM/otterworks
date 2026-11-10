"""Workspace share-policy API, GET/PUT /api/v1/workspace/share-policy (OTW-45, parent OTW-41).

Each test names the Given/When/Then acceptance criterion it covers.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest

from app.services.share_link_repository import (
    ShareLinkRepository,
    WorkspaceSharePolicyRepository,
)
from tests.conftest import TEST_JWT_SECRET

URL = "/api/v1/workspace/share-policy"


def _auth(user_id: uuid.UUID, *, roles: list[str] | None = None, workspace_id: str | None = None):
    claims: dict = {"user_id": str(user_id)}
    if roles is not None:
        claims["roles"] = roles
    if workspace_id is not None:
        claims["workspace_id"] = workspace_id
    token = jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner_headers(owner_id):
    return _auth(owner_id, roles=["OWNER"])


@pytest.fixture
def member_headers():
    return _auth(uuid.uuid4(), roles=["EDITOR"])


# Given a new workspace, When GET is called, Then default_days=30 and max_days=90.


async def test_new_workspace_get_returns_30_90_defaults(client, member_headers):
    resp = await client.get(URL, headers=member_headers)

    assert resp.status_code == 200
    assert resp.json() == {
        "workspace_id": "default",
        "default_days": 30,
        "max_days": 90,
        "updated_at": None,
        "updated_by": None,
    }


async def test_get_uses_callers_workspace(client, member_headers):
    resp = await client.get(URL, headers=_auth(uuid.uuid4(), workspace_id="ws-7"))

    assert resp.status_code == 200
    assert resp.json()["workspace_id"] == "ws-7"


# Given a user who is not a workspace owner ... Any authenticated user may GET.


async def test_any_authenticated_user_may_get(client, owner_headers, member_headers):
    await client.put(URL, json={"default_days": 14, "max_days": 60}, headers=owner_headers)

    resp = await client.get(URL, headers=member_headers)

    assert resp.status_code == 200
    assert (resp.json()["default_days"], resp.json()["max_days"]) == (14, 60)


async def test_unauthenticated_get_is_401(client):
    resp = await client.get(URL, auth=None)

    assert resp.status_code == 401


# Given a workspace owner, When they PUT a default between 1 and 90 days (no higher than
# the maximum), Then it is saved and used for new folder links.


@pytest.mark.parametrize(("default_days", "max_days"), [(1, 1), (7, 30), (30, 90), (90, 90)])
async def test_owner_put_valid_policy_is_saved(
    client, db_session, owner_headers, owner_id, default_days, max_days
):
    resp = await client.put(
        URL, json={"default_days": default_days, "max_days": max_days}, headers=owner_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert (body["default_days"], body["max_days"]) == (default_days, max_days)
    assert body["workspace_id"] == "default"
    assert body["updated_by"] == str(owner_id)
    assert body["updated_at"] is not None

    # New folder links read the effective policy from this repository.
    saved = await WorkspaceSharePolicyRepository(db_session).get("default")
    assert (saved.default_days, saved.max_days) == (default_days, max_days)

    get_resp = await client.get(URL, headers=owner_headers)
    assert get_resp.json() == body


async def test_owner_put_without_max_keeps_current_max(client, owner_headers):
    await client.put(URL, json={"default_days": 10, "max_days": 45}, headers=owner_headers)

    resp = await client.put(URL, json={"default_days": 20}, headers=owner_headers)

    assert resp.status_code == 200
    assert (resp.json()["default_days"], resp.json()["max_days"]) == (20, 45)


async def test_owner_put_only_changes_own_workspace(client, db_session, owner_id):
    resp = await client.put(
        URL,
        json={"default_days": 5, "max_days": 10},
        headers=_auth(owner_id, roles=["OWNER"], workspace_id="ws-a"),
    )

    assert resp.status_code == 200
    repo = WorkspaceSharePolicyRepository(db_session)
    assert (await repo.get("ws-a")).default_days == 5
    assert (await repo.get("default")).default_days == 30


async def test_legacy_owner_role_name_may_put(client, owner_id):
    resp = await client.put(
        URL, json={"default_days": 15, "max_days": 90}, headers=_auth(owner_id, roles=["ADMIN"])
    )

    assert resp.status_code == 200


# Given a workspace owner, When they try a default above 90, below 1, above the maximum,
# or "never"/null, Then 422.


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"default_days": 91, "max_days": 90}, id="default-above-90"),
        pytest.param({"default_days": 0, "max_days": 90}, id="default-below-1"),
        pytest.param({"default_days": -5, "max_days": 90}, id="default-negative"),
        pytest.param({"default_days": 60, "max_days": 30}, id="default-above-max"),
        pytest.param({"default_days": "never", "max_days": 90}, id="default-never"),
        pytest.param({"default_days": None, "max_days": 90}, id="default-null"),
        pytest.param({"max_days": 90}, id="default-missing"),
        pytest.param({"default_days": 30, "max_days": 91}, id="max-above-90"),
        pytest.param({"default_days": 30, "max_days": 0}, id="max-below-1"),
        pytest.param({"default_days": 30, "max_days": "never"}, id="max-never"),
        pytest.param({"default_days": 30, "max_days": None}, id="max-null"),
        pytest.param({"default_days": 30.5, "max_days": 90}, id="fractional-days"),
        pytest.param({"default_days": "30", "max_days": 90}, id="numeric-string"),
        pytest.param({"default_days": True, "max_days": 90}, id="boolean"),
        pytest.param({"default_days": 30, "max_days": 90, "never_expires": True}, id="extra-field"),
    ],
)
async def test_owner_put_invalid_policy_is_422_and_not_saved(
    client, db_session, owner_headers, body
):
    resp = await client.put(URL, json=body, headers=owner_headers)

    assert resp.status_code == 422
    saved = await WorkspaceSharePolicyRepository(db_session).get("default")
    assert (saved.default_days, saved.max_days, saved.updated_at) == (30, 90, None)


async def test_owner_put_default_above_stored_max_is_422(client, owner_headers):
    await client.put(URL, json={"default_days": 10, "max_days": 20}, headers=owner_headers)

    resp = await client.put(URL, json={"default_days": 21}, headers=owner_headers)

    assert resp.status_code == 422
    assert (await client.get(URL, headers=owner_headers)).json()["default_days"] == 10


# Given a user who is not a workspace owner, When they try PUT, Then 403.


@pytest.mark.parametrize("roles", [None, [], ["EDITOR"], ["VIEWER"], ["owner-ish"]])
async def test_non_owner_put_is_403_and_not_saved(client, db_session, roles):
    resp = await client.put(
        URL, json={"default_days": 10, "max_days": 20}, headers=_auth(uuid.uuid4(), roles=roles)
    )

    assert resp.status_code == 403
    saved = await WorkspaceSharePolicyRepository(db_session).get("default")
    assert (saved.default_days, saved.max_days) == (30, 90)


async def test_non_owner_put_with_invalid_body_is_still_403(client, member_headers):
    resp = await client.put(URL, json={"default_days": "never"}, headers=member_headers)

    assert resp.status_code == 403


async def test_unauthenticated_put_is_401(client):
    resp = await client.put(URL, json={"default_days": 10, "max_days": 20}, auth=None)

    assert resp.status_code == 401


async def test_owner_role_from_forged_token_is_ignored(client, owner_id):
    forged = jwt.encode(
        {"user_id": str(owner_id), "roles": ["OWNER"]}, "wrong-secret-pad-to-32-bytes!!!!", "HS256"
    )

    resp = await client.put(
        URL,
        json={"default_days": 10, "max_days": 20},
        headers={"Authorization": f"Bearer {forged}"},
    )

    assert resp.status_code == 401


# Given links that already exist, When the workspace default changes, Then their expiry
# does not change.


async def test_existing_links_keep_expiry_when_policy_changes(
    client, db_session, owner_headers, owner_id, folder_id
):
    expires_at = datetime.now(UTC) + timedelta(days=30)
    link = await ShareLinkRepository(db_session).create(
        resource_id=folder_id,
        workspace_id="default",
        created_by=owner_id,
        expires_at=expires_at,
    )
    link_id, before = link.id, (link.expires_at, link.expired_at)

    resp = await client.put(URL, json={"default_days": 3, "max_days": 7}, headers=owner_headers)
    assert resp.status_code == 200

    db_session.expire_all()
    reloaded = await ShareLinkRepository(db_session).get(link_id)
    assert (reloaded.expires_at, reloaded.expired_at) == before


# Hook point for OTW-46 (workspace_share_policy_changed audit event).


async def test_policy_change_calls_event_hook_with_old_and_new(client, owner_headers, owner_id):
    with patch("app.api.workspace.emit_policy_changed_event", new=AsyncMock()) as hook:
        resp = await client.put(
            URL, json={"default_days": 7, "max_days": 14}, headers=owner_headers
        )

    assert resp.status_code == 200
    hook.assert_awaited_once()
    old, new = hook.await_args.args
    assert (old.default_days, old.max_days) == (30, 90)
    assert (new.default_days, new.max_days) == (7, 14)
    assert hook.await_args.kwargs == {"actor_id": owner_id, "workspace_id": "default"}


async def test_rejected_change_does_not_call_event_hook(client, owner_headers, member_headers):
    with patch("app.api.workspace.emit_policy_changed_event", new=AsyncMock()) as hook:
        await client.put(URL, json={"default_days": 91}, headers=owner_headers)
        await client.put(URL, json={"default_days": 60, "max_days": 30}, headers=owner_headers)
        await client.put(URL, json={"default_days": 7}, headers=member_headers)

    hook.assert_not_awaited()
