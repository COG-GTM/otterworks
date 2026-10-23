"""QA audit: notification-service black-box tests through the API gateway.

Findings referenced here (NS-*) are documented in docs/qa/notification-service.md.
"""

import uuid

import pytest


pytestmark = pytest.mark.api_flow

NOTIFICATIONS = "/api/v1/notifications"
PREFERENCES = "/api/v1/preferences"


def _list(api_client, user, **params):
    response = api_client.client.get(NOTIFICATIONS, headers=user.auth_headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _unread(api_client, user) -> int:
    response = api_client.client.get(f"{NOTIFICATIONS}/unread-count", headers=user.auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["userId"] == user.id
    return body["unreadCount"]


def _upload_file(api_client, owner, name="qa-notify.txt"):
    response = api_client.client.post(
        "/api/v1/files/upload",
        headers=owner.auth_headers,
        files={"file": (name, b"qa notification body", "text/plain")},
    )
    assert response.status_code == 201, response.text
    file_id = response.json()["file"]["id"]
    api_client.created_files.append(file_id)
    return file_id


def _share(api_client, owner, recipient, file_id):
    response = api_client.client.post(
        f"/api/v1/files/{file_id}/share",
        headers=owner.auth_headers,
        json={"shared_with": recipient.id, "permission": "viewer", "shared_by": owner.id},
    )
    assert response.status_code in {200, 201}, response.text


def _wait_for_share_notification(api_client, recipient, file_id):
    def probe():
        return [n for n in _list(api_client, recipient, page_size=100)["data"] if n["resourceId"] == file_id]

    matches = api_client.poll_until(
        probe, timeout_seconds=45, description=f"file_shared notification for {file_id}"
    )
    return matches[0]


@pytest.fixture
def shared_notification(api_client):
    owner = api_client.register_user("qa-notif-owner")
    recipient = api_client.register_user("qa-notif-recipient")
    file_id = _upload_file(api_client, owner)
    _share(api_client, owner, recipient, file_id)
    notification = _wait_for_share_notification(api_client, recipient, file_id)
    return owner, recipient, file_id, notification


# --- auth / identity ---------------------------------------------------------


def test_notifications_require_authentication(api_client):
    for method, path in [
        ("GET", NOTIFICATIONS),
        ("GET", f"{NOTIFICATIONS}/unread-count"),
        ("PUT", f"{NOTIFICATIONS}/read-all"),
        ("GET", PREFERENCES),
    ]:
        response = api_client.client.request(method, path)
        assert response.status_code == 401, f"{method} {path}: {response.status_code}"


def test_gateway_identity_wins_over_user_id_query_param(api_client, shared_notification):
    _, recipient, file_id, _ = shared_notification
    intruder = api_client.register_user("qa-notif-intruder")
    data = _list(api_client, intruder, user_id=recipient.id, page_size=100)
    assert all(n["userId"] == intruder.id for n in data["data"])
    assert not any(n["resourceId"] == file_id for n in data["data"])


def test_spoofed_x_user_id_header_is_stripped(api_client, shared_notification):
    _, recipient, file_id, _ = shared_notification
    intruder = api_client.register_user("qa-notif-spoof")
    response = api_client.client.get(
        NOTIFICATIONS,
        headers={**intruder.auth_headers, "X-User-ID": recipient.id},
        params={"page_size": 100},
    )
    assert response.status_code == 200, response.text
    assert not any(n["resourceId"] == file_id for n in response.json()["data"])


# --- list / pagination ---------------------------------------------------------


def test_new_user_has_empty_paginated_inbox(api_client):
    user = api_client.register_user("qa-notif-empty")
    data = _list(api_client, user)
    assert data == {"data": [], "total": 0, "page": 1, "pageSize": 20} or (
        data["data"] == [] and data["total"] == 0 and data["page"] == 1
    )
    assert _unread(api_client, user) == 0


def test_pagination_splits_notifications_across_pages(api_client):
    owner = api_client.register_user("qa-notif-page-owner")
    recipient = api_client.register_user("qa-notif-page-recipient")
    file_ids = [_upload_file(api_client, owner, f"page-{i}.txt") for i in range(3)]
    for file_id in file_ids:
        _share(api_client, owner, recipient, file_id)
    api_client.poll_until(
        lambda: _list(api_client, recipient)["total"],
        predicate=lambda total: total >= 3,
        timeout_seconds=45,
        description="three share notifications",
    )

    page1 = _list(api_client, recipient, page=1, page_size=2)
    page2 = _list(api_client, recipient, page=2, page_size=2)
    beyond = _list(api_client, recipient, page=10, page_size=2)
    assert page1["total"] == page2["total"] == 3
    assert len(page1["data"]) == 2 and len(page2["data"]) == 1
    assert {n["id"] for n in page1["data"]}.isdisjoint({n["id"] for n in page2["data"]})
    assert beyond["data"] == []
    created = [n["createdAt"] for n in page1["data"] + page2["data"]]
    assert created == sorted(created, reverse=True), "notifications should be newest first"


@pytest.mark.xfail(reason="FINDING NS-4: page<=0 / page_size<=0 are not validated (500 or silent clamp instead of 400)", strict=False)
@pytest.mark.parametrize("params", [{"page": 0}, {"page": -1}, {"page_size": 0}])
def test_non_positive_pagination_is_rejected(api_client, params):
    user = api_client.register_user("qa-notif-badpage")
    response = api_client.client.get(NOTIFICATIONS, headers=user.auth_headers, params=params)
    assert response.status_code == 400, response.text


# --- event-triggered notification + read lifecycle ----------------------------


def test_share_creates_unread_notification_for_recipient_only(api_client, shared_notification):
    owner, recipient, file_id, notification = shared_notification
    assert notification["type"] == "file_shared"
    assert notification["userId"] == recipient.id
    assert notification["actorId"] == owner.id
    assert notification["resourceType"] == "file"
    assert notification["read"] is False
    assert _unread(api_client, recipient) >= 1
    assert not any(n["resourceId"] == file_id for n in _list(api_client, owner, page_size=100)["data"])


def test_mark_read_mark_all_read_and_delete_lifecycle(api_client):
    owner = api_client.register_user("qa-notif-life-owner")
    recipient = api_client.register_user("qa-notif-life-recipient")
    first, second = _upload_file(api_client, owner, "one.txt"), _upload_file(api_client, owner, "two.txt")
    _share(api_client, owner, recipient, first)
    _share(api_client, owner, recipient, second)
    n1 = _wait_for_share_notification(api_client, recipient, first)
    _wait_for_share_notification(api_client, recipient, second)
    assert _unread(api_client, recipient) == 2

    get_one = api_client.client.get(f"{NOTIFICATIONS}/{n1['id']}", headers=recipient.auth_headers)
    assert get_one.status_code == 200 and get_one.json()["id"] == n1["id"]

    mark = api_client.client.put(f"{NOTIFICATIONS}/{n1['id']}/read", headers=recipient.auth_headers)
    assert mark.status_code == 204, mark.text
    reread = api_client.client.get(f"{NOTIFICATIONS}/{n1['id']}", headers=recipient.auth_headers)
    assert reread.json()["read"] is True
    assert _unread(api_client, recipient) == 1

    mark_all = api_client.client.put(f"{NOTIFICATIONS}/read-all", headers=recipient.auth_headers)
    assert mark_all.status_code == 200, mark_all.text
    assert mark_all.json()["markedCount"] == 1
    assert _unread(api_client, recipient) == 0
    assert all(n["read"] for n in _list(api_client, recipient)["data"])

    again = api_client.client.put(f"{NOTIFICATIONS}/read-all", headers=recipient.auth_headers)
    assert again.json()["markedCount"] == 0

    delete = api_client.client.delete(f"{NOTIFICATIONS}/{n1['id']}", headers=recipient.auth_headers)
    assert delete.status_code == 204, delete.text
    gone = api_client.client.get(f"{NOTIFICATIONS}/{n1['id']}", headers=recipient.auth_headers)
    assert gone.status_code == 404
    assert _list(api_client, recipient)["total"] == 1


def test_unknown_notification_returns_404(api_client):
    user = api_client.register_user("qa-notif-missing")
    missing = str(uuid.uuid4())
    assert api_client.client.get(f"{NOTIFICATIONS}/{missing}", headers=user.auth_headers).status_code == 404
    assert api_client.client.put(f"{NOTIFICATIONS}/{missing}/read", headers=user.auth_headers).status_code == 404


@pytest.mark.xfail(reason="FINDING NS-13: DELETE /api/v1/notifications/{id} returns 204 for a nonexistent id (unconditional DeleteItem)", strict=True)
def test_delete_unknown_notification_returns_404(api_client):
    user = api_client.register_user("qa-notif-missing-del")
    response = api_client.client.delete(f"{NOTIFICATIONS}/{uuid.uuid4()}", headers=user.auth_headers)
    assert response.status_code == 404, response.status_code


# --- ownership (findings) -----------------------------------------------------


@pytest.mark.xfail(reason="FINDING NS-1: GET /api/v1/notifications/{id} returns another user's notification", strict=True)
def test_other_user_cannot_read_notification_by_id(api_client, shared_notification):
    _, _, _, notification = shared_notification
    intruder = api_client.register_user("qa-notif-idor-get")
    response = api_client.client.get(f"{NOTIFICATIONS}/{notification['id']}", headers=intruder.auth_headers)
    assert response.status_code in {403, 404}, response.text


@pytest.mark.xfail(reason="FINDING NS-2: PUT /api/v1/notifications/{id}/read lets any user mark another user's notification", strict=True)
def test_other_user_cannot_mark_notification_read(api_client, shared_notification):
    _, recipient, _, notification = shared_notification
    intruder = api_client.register_user("qa-notif-idor-read")
    response = api_client.client.put(f"{NOTIFICATIONS}/{notification['id']}/read", headers=intruder.auth_headers)
    still_unread = api_client.client.get(f"{NOTIFICATIONS}/{notification['id']}", headers=recipient.auth_headers)
    assert response.status_code in {403, 404}, response.text
    assert still_unread.json()["read"] is False


@pytest.mark.xfail(reason="FINDING NS-3: DELETE /api/v1/notifications/{id} lets any user delete another user's notification", strict=True)
def test_other_user_cannot_delete_notification(api_client, shared_notification):
    _, recipient, _, notification = shared_notification
    intruder = api_client.register_user("qa-notif-idor-del")
    response = api_client.client.delete(f"{NOTIFICATIONS}/{notification['id']}", headers=intruder.auth_headers)
    survivor = api_client.client.get(f"{NOTIFICATIONS}/{notification['id']}", headers=recipient.auth_headers)
    assert response.status_code in {403, 404}, response.text
    assert survivor.status_code == 200


# --- preferences ----------------------------------------------------------------


def test_default_preferences(api_client):
    user = api_client.register_user("qa-notif-pref-default")
    response = api_client.client.get(PREFERENCES, headers=user.auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["userId"] == user.id
    assert set(body["channels"]) >= {"file_shared", "comment_added", "document_edited", "user_mentioned"}


def test_preference_update_persists_and_merges(api_client):
    user = api_client.register_user("qa-notif-pref-persist")
    put = api_client.client.put(
        PREFERENCES,
        headers=user.auth_headers,
        json={"userId": user.id, "eventType": "file_shared", "channels": ["IN_APP"]},
    )
    assert put.status_code == 204, put.text
    put2 = api_client.client.put(
        PREFERENCES,
        headers=user.auth_headers,
        json={"userId": user.id, "eventType": "comment_added", "channels": []},
    )
    assert put2.status_code == 204, put2.text

    channels = api_client.client.get(PREFERENCES, headers=user.auth_headers).json()["channels"]
    assert channels["file_shared"] == ["IN_APP"]
    assert channels["comment_added"] == []
    assert "IN_APP" in channels["document_edited"]


def _share_with_in_app_disabled(api_client):
    owner = api_client.register_user("qa-notif-pref-owner")
    recipient = api_client.register_user("qa-notif-pref-recipient")
    put = api_client.client.put(
        PREFERENCES,
        headers=recipient.auth_headers,
        json={"userId": recipient.id, "eventType": "file_shared", "channels": ["EMAIL"]},
    )
    assert put.status_code == 204, put.text
    muted_file = _upload_file(api_client, owner, "muted.txt")
    _share(api_client, owner, recipient, muted_file)
    # Control share to a second recipient proves the event pipeline ran.
    control = api_client.register_user("qa-notif-pref-control")
    _share(api_client, owner, control, muted_file)
    _wait_for_share_notification(api_client, control, muted_file)
    return recipient, muted_file


def test_in_app_disabled_is_not_recorded_as_in_app_delivery(api_client):
    recipient, muted_file = _share_with_in_app_disabled(api_client)
    matches = [n for n in _list(api_client, recipient, page_size=100)["data"] if n["resourceId"] == muted_file]
    for notification in matches:
        assert "in_app" not in notification["deliveredVia"]


@pytest.mark.xfail(reason="FINDING NS-10: notifications are persisted and listed in the inbox even when IN_APP is disabled for the event type", strict=True)
def test_in_app_disabled_hides_share_from_inbox(api_client):
    recipient, muted_file = _share_with_in_app_disabled(api_client)
    data = _list(api_client, recipient, page_size=100)["data"]
    assert not any(n["resourceId"] == muted_file for n in data)


@pytest.mark.xfail(reason="FINDING NS-9: client-app NotificationBell reads `count` but unread-count returns `unreadCount`, so the bell badge never shows", strict=True)
def test_unread_count_matches_client_app_contract(api_client):
    user = api_client.register_user("qa-notif-bell")
    body = api_client.client.get(f"{NOTIFICATIONS}/unread-count", headers=user.auth_headers).json()
    assert "count" in body, body


@pytest.mark.xfail(reason="FINDING NS-11: client-app sends `pageSize` but notification-service only reads `page_size`", strict=True)
def test_client_app_page_size_param_is_honoured(api_client):
    user = api_client.register_user("qa-notif-pagesize")
    body = _list(api_client, user, page=1, pageSize=5)
    assert body["pageSize"] == 5, body


@pytest.mark.xfail(reason="FINDING NS-5: PUT /api/v1/preferences trusts body userId, so a user can overwrite another user's preferences", strict=True)
def test_cannot_overwrite_other_users_preferences(api_client):
    victim = api_client.register_user("qa-notif-pref-victim")
    attacker = api_client.register_user("qa-notif-pref-attacker")
    api_client.client.put(
        PREFERENCES,
        headers=attacker.auth_headers,
        json={"userId": victim.id, "eventType": "file_shared", "channels": []},
    )
    channels = api_client.client.get(PREFERENCES, headers=victim.auth_headers).json()["channels"]
    assert channels["file_shared"] != []


@pytest.mark.xfail(reason="FINDING NS-7: malformed / unknown-channel preference payloads return 500 instead of 400", strict=False)
@pytest.mark.parametrize(
    "payload",
    [
        {"eventType": "file_shared", "channels": ["IN_APP"]},
        {"userId": "x", "eventType": "file_shared", "channels": ["CARRIER_PIGEON"]},
    ],
    ids=["missing-userId", "unknown-channel"],
)
def test_malformed_preferences_rejected_with_400(api_client, payload):
    user = api_client.register_user("qa-notif-pref-bad")
    response = api_client.client.put(PREFERENCES, headers=user.auth_headers, json=payload)
    assert response.status_code == 400, response.text


@pytest.mark.xfail(reason="FINDING NS-6: client-app calls PATCH /notifications/{id}/read and POST /notifications/read-all; backend only routes PUT", strict=True)
def test_client_app_mark_read_verbs_are_routed(api_client, shared_notification):
    _, recipient, _, notification = shared_notification
    patch = api_client.client.patch(f"{NOTIFICATIONS}/{notification['id']}/read", headers=recipient.auth_headers)
    post = api_client.client.post(f"{NOTIFICATIONS}/read-all", headers=recipient.auth_headers)
    assert patch.status_code == 200, patch.text
    assert post.status_code == 200, post.text
