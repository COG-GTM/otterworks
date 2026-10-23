"""QA admin-audit functional tests through the API gateway.

Covers admin-service (/api/v1/admin: users, audit-logs, settings, features,
incidents) and audit-service (/api/v1/audit). Devin/Slack integrations are
never exercised with valid values: only authz and validation rejections.
Findings QA-AA-N are documented in docs/qa/admin-audit.md.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.api_flow

JWT_SECRET = os.getenv("JWT_SECRET", "otterworks-local-dev-jwt-secret-change-me-in-production")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint_token(role: str, user_id: str | None = None, email: str | None = None) -> tuple[str, str, str]:
    user_id = user_id or str(uuid.uuid4())
    email = email or f"qa-{role}-{user_id[:8]}@otterworks.test"
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({
        "sub": user_id, "user_id": user_id, "email": email, "role": role, "roles": [role],
        "iat": now, "exp": now + 3600,
    }).encode())
    sig = _b64(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}", user_id, email


def headers_for(role: str, **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(role, **kwargs)[0]}"}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def admin(api_client):
    token, user_id, email = mint_token("admin")
    return {"headers": {"Authorization": f"Bearer {token}"}, "id": user_id, "email": email}


@pytest.fixture
def target_user(api_client, admin):
    resp = api_client.client.get("/api/v1/admin/users", headers=admin["headers"], params={"per_page": 100})
    assert resp.status_code == 200, resp.text
    users = [u for u in resp.json()["users"] if u["role"] in {"viewer", "editor"} and u["status"] == "active"]
    if not users:
        pytest.skip("no seeded active viewer/editor admin_users (run scripts/seed.py)")
    user = users[0]
    yield user
    api_client.client.put(f"/api/v1/admin/users/{user['id']}/activate", headers=admin["headers"])
    api_client.client.put(f"/api/v1/admin/users/{user['id']}", headers=admin["headers"],
                          json={"user": {"role": user["role"]}})


# ── admin-service: users ───────────────────────────────────────────────────


def test_admin_user_lifecycle_is_audited_with_actor_and_timestamps(api_client, admin, target_user):
    c, h, uid = api_client.client, admin["headers"], target_user["id"]
    started = datetime.now(UTC) - timedelta(seconds=5)

    search = c.get("/api/v1/admin/users", headers=h, params={"q": target_user["email"]})
    assert search.status_code == 200
    assert uid in [u["id"] for u in search.json()["users"]]

    detail = c.get(f"/api/v1/admin/users/{uid}", headers=h)
    assert detail.status_code == 200
    assert detail.json()["email"] == target_user["email"]

    new_role = "editor" if target_user["role"] == "viewer" else "viewer"
    role_resp = c.put(f"/api/v1/admin/users/{uid}", headers=h, json={"user": {"role": new_role}})
    assert role_resp.status_code == 200, role_resp.text
    assert role_resp.json()["role"] == new_role

    suspended = c.put(f"/api/v1/admin/users/{uid}/suspend", headers=h, json={"reason": "qa-admin-audit"})
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    activated = c.put(f"/api/v1/admin/users/{uid}/activate", headers=h)
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    logs = c.get("/api/v1/admin/audit-logs", headers=h,
                 params={"resource_type": "AdminUser", "resource_id": uid, "actor_id": admin["id"]})
    assert logs.status_code == 200, logs.text
    entries = logs.json()["audit_logs"]
    actions = [e["action"] for e in entries]
    assert actions[:3] == ["user.activated", "user.suspended", "user.updated"]
    for entry in entries[:3]:
        assert entry["actor_id"] == admin["id"]
        assert entry["actor_email"] == admin["email"]
        assert started <= parse_ts(entry["created_at"]) <= datetime.now(UTC) + timedelta(seconds=5)
    assert entries[1]["changes_made"]["reason"] == "qa-admin-audit"


@pytest.mark.parametrize("role", ["viewer", "editor", "user"])
def test_admin_user_mutations_forbidden_for_non_admin_roles(api_client, target_user, role):
    h = headers_for(role)
    c, uid = api_client.client, target_user["id"]
    assert c.get("/api/v1/admin/users", headers=h).status_code == 403
    assert c.put(f"/api/v1/admin/users/{uid}/suspend", headers=h).status_code == 403
    assert c.put(f"/api/v1/admin/users/{uid}", headers=h, json={"user": {"role": "super_admin"}}).status_code == 403


def test_admin_users_require_token_and_reject_bad_signature(api_client):
    c = api_client.client
    assert c.get("/api/v1/admin/users").status_code == 401
    token = mint_token("admin")[0]
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert c.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


def test_admin_user_update_validation(api_client, admin, target_user):
    c, h = api_client.client, admin["headers"]
    bad = c.put(f"/api/v1/admin/users/{target_user['id']}", headers=h, json={"user": {"role": "god_mode"}})
    assert bad.status_code == 422
    assert c.get(f"/api/v1/admin/users/{uuid.uuid4()}", headers=h).status_code == 404
    assert c.put(f"/api/v1/admin/users/{uuid.uuid4()}/suspend", headers=h).status_code == 404


# ── admin-service: audit logs ──────────────────────────────────────────────


def test_admin_audit_logs_filters_and_validation(api_client, admin):
    c, h = api_client.client, admin["headers"]
    page = c.get("/api/v1/admin/audit-logs", headers=h, params={"per_page": 5})
    assert page.status_code == 200
    body = page.json()
    assert len(body["audit_logs"]) <= 5
    stamps = [parse_ts(e["created_at"]) for e in body["audit_logs"]]
    assert stamps == sorted(stamps, reverse=True)

    filtered = c.get("/api/v1/admin/audit-logs", headers=h, params={"action_type": "user.suspended"})
    assert all(e["action"] == "user.suspended" for e in filtered.json()["audit_logs"])

    assert c.get("/api/v1/admin/audit-logs", headers=h, params={"since": "not-a-date"}).status_code == 400
    assert c.get(f"/api/v1/admin/audit-logs/{uuid.uuid4()}", headers=h).status_code == 404


@pytest.mark.xfail(strict=True, reason="QA-AA-2: /api/v1/admin/audit-logs has no require_admin!; viewers read the admin trail")
def test_admin_audit_logs_forbidden_for_viewer(api_client):
    resp = api_client.client.get("/api/v1/admin/audit-logs", headers=headers_for("viewer"))
    assert resp.status_code == 403


# ── admin-service: settings / features / incidents ─────────────────────────


def test_admin_settings_authz_validation_and_secrecy(api_client, admin):
    c, h = api_client.client, admin["headers"]
    creds = c.get("/api/v1/admin/settings/devin_credentials", headers=h)
    assert creds.status_code == 200
    assert "api_key" not in creds.json() or not isinstance(creds.json().get("api_key"), str)

    slack = c.get("/api/v1/admin/settings/slack_notifications", headers=h)
    assert slack.status_code == 200
    assert "webhook_url" not in slack.json() and "bot_token" not in slack.json()

    viewer = headers_for("viewer")
    assert c.put("/api/v1/admin/settings/slack_notifications", headers=viewer, json={"enabled": True}).status_code == 403
    assert c.put("/api/v1/admin/settings/devin_credentials", headers=viewer,
                 json={"api_key": "x", "org_id": "y"}).status_code == 403
    assert c.put("/api/v1/admin/settings/auto_investigate", headers=viewer, json={"enabled": True}).status_code == 403

    evil = c.put("/api/v1/admin/settings/slack_notifications", headers=h,
                 json={"webhook_url": "https://attacker.example.com/hook"})
    assert evil.status_code == 400
    empty = c.put("/api/v1/admin/settings/slack_notifications", headers=h, json={})
    assert empty.status_code == 400


def test_admin_feature_flag_crud_is_audited(api_client, admin):
    c, h = api_client.client, admin["headers"]
    name = f"qa_admin_audit_{uuid.uuid4().hex[:8]}"
    created = c.post("/api/v1/admin/features", headers=h,
                     json={"feature": {"name": name, "enabled": False, "rollout_percentage": 10}})
    assert created.status_code == 201, created.text
    flag_id = created.json()["id"]
    try:
        assert c.post("/api/v1/admin/features", headers=headers_for("editor"),
                      json={"feature": {"name": name + "_x", "enabled": True}}).status_code == 403
        bad = c.post("/api/v1/admin/features", headers=h,
                     json={"feature": {"name": name + "_bad", "rollout_percentage": 150}})
        assert bad.status_code == 422
        updated = c.put(f"/api/v1/admin/features/{flag_id}", headers=h, json={"feature": {"enabled": True}})
        assert updated.status_code == 200
        assert updated.json()["enabled"] is True
    finally:
        assert c.delete(f"/api/v1/admin/features/{flag_id}", headers=h).status_code in {200, 204}

    logs = c.get("/api/v1/admin/audit-logs", headers=h, params={"actor_id": admin["id"]}).json()["audit_logs"]
    actions = {e["action"] for e in logs}
    assert {"feature_flag.created", "feature_flag.updated", "feature_flag.deleted"} <= actions


def test_admin_incidents_viewer_cannot_create_or_trigger_devin(api_client, admin):
    c = api_client.client
    listing = c.get("/api/v1/admin/incidents", headers=admin["headers"])
    assert listing.status_code == 200
    viewer = headers_for("viewer")
    resp = c.post("/api/v1/admin/incidents", headers=viewer,
                  json={"incident": {"title": "qa", "description": "qa", "severity": "low"}})
    assert resp.status_code == 403
    assert c.post(f"/api/v1/admin/incidents/{uuid.uuid4()}/trigger_session", headers=viewer).status_code == 403
    assert c.get(f"/api/v1/admin/incidents/{uuid.uuid4()}", headers=admin["headers"]).status_code == 404


def test_admin_alert_ingest_and_chaos_require_shared_secret(api_client):
    c = api_client.client
    ingest = c.post("/api/v1/admin/alerts/ingest", json={"alert_name": "qa", "service": "file-service"})
    assert ingest.status_code in {401, 403}
    chaos = c.post("/api/v1/admin/chaos", json={"scenario": "qa"})
    assert chaos.status_code in {401, 403, 404}


# ── audit-service ──────────────────────────────────────────────────────────


def test_audit_service_write_then_query_by_filters(api_client):
    user = api_client.register_user("qa-audit")
    c, h = api_client.client, user.auth_headers
    resource = f"qa-doc-{uuid.uuid4().hex[:8]}"
    before = datetime.now(UTC) - timedelta(seconds=5)
    payload = {"userId": user.id, "action": "document.viewed", "resourceType": "document",
               "resourceId": resource, "details": {"source": "qa"}, "ipAddress": "10.0.0.9", "userAgent": "qa"}
    created = c.post("/api/v1/audit/events", headers=h, json=payload)
    assert created.status_code == 201, created.text
    event = created.json()
    assert event["userId"] == user.id
    assert before <= parse_ts(event["timestamp"]) <= datetime.now(UTC) + timedelta(seconds=5)

    fetched = c.get(f"/api/v1/audit/events/{event['id']}", headers=h)
    assert fetched.status_code == 200
    assert fetched.json()["details"] == {"source": "qa"}

    for params in ({"user_id": user.id}, {"resource": resource}, {"action": "document.viewed", "resource": resource},
                   {"resource_type": "document", "user_id": user.id}):
        page = c.get("/api/v1/audit/events", headers=h, params=params)
        assert page.status_code == 200, params
        assert event["id"] in [e["id"] for e in page.json()["events"]], params

    later = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    none = c.get("/api/v1/audit/events", headers=h, params={"user_id": user.id, "from": later})
    assert none.json()["total"] == 0

    history = c.get(f"/api/v1/audit/resources/{resource}/history", headers=h)
    assert history.status_code == 200


def test_audit_service_validation_paging_and_auth(api_client):
    user = api_client.register_user("qa-audit-val")
    c, h = api_client.client, user.auth_headers
    for missing in ("userId", "action", "resourceType", "resourceId"):
        body = {"userId": user.id, "action": "a", "resourceType": "t", "resourceId": "r"}
        body[missing] = " "
        resp = c.post("/api/v1/audit/events", headers=h, json=body)
        assert resp.status_code == 400, missing
    assert c.get(f"/api/v1/audit/events/{uuid.uuid4()}", headers=h).status_code == 404
    assert c.get("/api/v1/audit/events", headers=h, params={"from": "garbage"}).status_code == 400
    clamped = c.get("/api/v1/audit/events", headers=h, params={"size": 500})
    assert clamped.status_code == 200 and clamped.json()["pageSize"] == 100
    assert c.get("/api/v1/audit/events").status_code == 401
    assert c.post("/api/v1/audit/events", json={"userId": "x", "action": "a", "resourceType": "t",
                                               "resourceId": "r"}).status_code == 401


@pytest.mark.xfail(strict=True, reason="QA-AA-7: audit-service accepts page=0 and echoes it instead of rejecting/clamping")
def test_audit_service_rejects_page_zero(api_client):
    user = api_client.register_user("qa-audit-page")
    resp = api_client.client.get("/api/v1/audit/events", headers=user.auth_headers, params={"page": 0})
    assert resp.status_code == 400 or resp.json()["page"] == 1


@pytest.mark.xfail(strict=True, reason="QA-AA-4: audit-service trusts body userId; any user can forge another actor")
def test_audit_service_rejects_forged_actor(api_client):
    user = api_client.register_user("qa-audit-forge")
    resp = api_client.client.post("/api/v1/audit/events", headers=user.auth_headers, json={
        "userId": "ceo-" + uuid.uuid4().hex[:6], "action": "qa.forged", "resourceType": "t", "resourceId": "r"})
    assert resp.status_code in {400, 403} or resp.json()["userId"] == user.id


@pytest.mark.xfail(strict=True, reason="QA-AA-6: SnsConsumer only maps file_shared; uploads are stored as system/unknown")
def test_client_file_upload_reaches_audit_trail_with_actor(api_client):
    user = api_client.register_user("qa-audit-upload")
    c, h = api_client.client, user.auth_headers
    up = c.post("/api/v1/files/upload", headers=h, files={"file": ("qa-audit.txt", b"qa", "text/plain")})
    assert up.status_code == 201, up.text
    api_client.created_files.append(up.json()["file"]["id"])
    file_id = up.json()["file"]["id"]

    def found():
        page = c.get("/api/v1/audit/events", headers=h, params={"user_id": user.id}).json()
        return [e for e in page["events"] if e["resourceId"] == file_id] or None

    events = api_client.poll_until(found, timeout_seconds=20, interval_seconds=2, description="upload audit event")
    assert events and events[0]["userId"] == user.id
