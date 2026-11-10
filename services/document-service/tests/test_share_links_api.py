"""OTW-20: expiring share links with workspace default and per-link override.

Test names carry the OTW-20 acceptance criterion they cover.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.share_link import ShareLink
from app.services import event_publisher as publisher_module
from app.services.share_link import ShareLinkService
from app.services.share_link_store import ShareLinkStore
from tests.conftest import TEST_JWT_SECRET


@pytest.fixture
def audit_events(monkeypatch):
    events: list[dict] = []

    async def _capture(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(publisher_module.event_publisher, "publish_audit", _capture)
    return events


def _workspace_owner_headers(user_id: uuid.UUID | None = None) -> dict[str, str]:
    token = jwt.encode(
        {"user_id": str(user_id or uuid.uuid4()), "roles": ["ADMIN"]},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_document(client, owner_id) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Shared doc", "content": "Secret body", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_policy(client, default=7, minimum=1, maximum=30):
    return await client.put(
        "/api/v1/documents/share-policy",
        json={
            "default_expiry_days": default,
            "min_expiry_days": minimum,
            "max_expiry_days": maximum,
        },
        headers=_workspace_owner_headers(),
    )


async def test_ac1_workspace_owner_sets_default_and_bounds(client, audit_events):
    resp = await _set_policy(client, default=5, minimum=2, maximum=10)
    assert resp.status_code == 200
    assert resp.json()["default_expiry_days"] == 5
    got = await client.get("/api/v1/documents/share-policy")
    assert got.json()["max_expiry_days"] == 10
    assert audit_events[-1]["action"] == "share_policy_update"
    assert audit_events[-1]["details"]["newValue"] == "default=5d;min=2d;max=10d"


async def test_ac1_non_workspace_owner_cannot_change_policy(client):
    resp = await client.put(
        "/api/v1/documents/share-policy",
        json={"default_expiry_days": 3, "min_expiry_days": 1, "max_expiry_days": 30},
    )
    assert resp.status_code == 403


async def test_ac1_policy_with_default_outside_bounds_is_rejected(client):
    resp = await _set_policy(client, default=40, minimum=1, maximum=30)
    assert resp.status_code == 422


async def test_ac2_ac9_new_link_uses_default_and_is_persisted(
    client, owner_id, db_session, audit_events
):
    await _set_policy(client, default=7)
    doc_id = await _create_document(client, owner_id)
    resp = await client.post(f"/api/v1/documents/{doc_id}/share")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    created = datetime.fromisoformat(body["created_at"])
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires - created == timedelta(days=7)
    assert body["created_by"] == str(owner_id)
    assert len(body["token"]) >= 32
    assert body["token"] != ShareLinkService().mint_token(doc_id)

    row = (await db_session.execute(select(ShareLink))).scalar_one()
    assert row.token == body["token"]
    assert audit_events[-1]["action"] == "share_link_create"
    assert audit_events[-1]["user_id"] == str(owner_id)
    assert audit_events[-1]["details"]["workspace"] == "default"


async def test_ac9_tokens_are_random_per_link(client, owner_id):
    doc_id = await _create_document(client, owner_id)
    first = await client.post(f"/api/v1/documents/{doc_id}/share")
    second = await client.post(f"/api/v1/documents/{doc_id}/share")
    assert first.json()["token"] != second.json()["token"]


async def test_ac3_override_within_bounds(client, owner_id):
    doc_id = await _create_document(client, owner_id)
    resp = await client.post(
        f"/api/v1/documents/{doc_id}/share", json={"expires_in_days": 14}
    )
    body = resp.json()
    delta = datetime.fromisoformat(body["expires_at"]) - datetime.fromisoformat(
        body["created_at"]
    )
    assert delta == timedelta(days=14)


@pytest.mark.parametrize("days", [0, 31, -1])
async def test_ac5_override_outside_bounds_is_rejected(client, owner_id, db_session, days):
    doc_id = await _create_document(client, owner_id)
    resp = await client.post(
        f"/api/v1/documents/{doc_id}/share", json={"expires_in_days": days}
    )
    assert resp.status_code == 422
    assert (await db_session.execute(select(ShareLink))).first() is None


async def test_ac4_owner_changes_expiry_and_change_is_audited(client, owner_id, audit_events):
    doc_id = await _create_document(client, owner_id)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    resp = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['id']}",
        json={"expires_in_days": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["expires_at"] != link["expires_at"]
    event = audit_events[-1]
    assert event["action"] == "share_link_expiry_change"
    assert event["details"]["oldValue"] != event["details"]["newValue"]


async def test_ac5_expiry_change_outside_bounds_leaves_link_unchanged(client, owner_id):
    doc_id = await _create_document(client, owner_id)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    resp = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['id']}",
        json={"expires_in_days": 90},
    )
    assert resp.status_code == 422
    listed = (await client.get(f"/api/v1/documents/{doc_id}/share-links")).json()
    assert listed[0]["expires_at"] == link["expires_at"]


async def test_ac4_only_document_owner_can_change_expiry(client, owner_id):
    doc_id = await _create_document(client, owner_id)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    other = jwt.encode({"user_id": str(uuid.uuid4())}, TEST_JWT_SECRET, algorithm="HS256")
    resp = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['id']}",
        json={"expires_in_days": 2},
        headers={"Authorization": f"Bearer {other}"},
    )
    assert resp.status_code == 403


async def _expire(db_session, link_id: str) -> None:
    row = await db_session.get(ShareLink, uuid.UUID(link_id))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()


async def test_live_link_returns_document(client, owner_id):
    doc_id = await _create_document(client, owner_id)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    resp = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": link["token"]},
        auth=None,
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "Secret body"


async def test_ac6_ac10_expired_link_returns_410_without_content_and_is_audited_once(
    client, owner_id, db_session, audit_events
):
    doc_id = await _create_document(client, owner_id)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    await _expire(db_session, link["id"])
    params = {"document_id": doc_id, "token": link["token"]}

    for _ in range(2):
        resp = await client.get("/api/v1/documents/shared", params=params, auth=None)
        assert resp.status_code == 410
        assert "Secret body" not in resp.text

    expiries = [e for e in audit_events if e["action"] == "share_link_expire"]
    assert len(expiries) == 1
    assert expiries[0]["details"]["newValue"] == "expired"


async def test_ac7_policy_change_does_not_extend_expired_link(client, owner_id, db_session):
    doc_id = await _create_document(client, owner_id)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    await _expire(db_session, link["id"])
    await _set_policy(client, default=30, minimum=1, maximum=30)
    resp = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": link["token"]},
        auth=None,
    )
    assert resp.status_code == 410
    patch = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['id']}",
        json={"expires_in_days": 5},
    )
    assert patch.status_code == 410


async def test_ac8_pre_existing_stateless_links_are_not_expired(client, owner_id, monkeypatch):
    monkeypatch.setattr(
        settings, "share_link_legacy_cutoff", datetime.now(UTC) + timedelta(days=1)
    )
    doc_id = await _create_document(client, owner_id)
    await _set_policy(client, default=1, minimum=1, maximum=1)
    legacy_token = ShareLinkService().mint_token(doc_id)
    resp = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": legacy_token},
        auth=None,
    )
    assert resp.status_code == 200


async def test_stateless_token_rejected_for_documents_created_after_cutoff(
    client, owner_id, monkeypatch
):
    monkeypatch.setattr(
        settings, "share_link_legacy_cutoff", datetime.now(UTC) - timedelta(days=1)
    )
    doc_id = await _create_document(client, owner_id)
    resp = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": ShareLinkService().mint_token(doc_id)},
        auth=None,
    )
    assert resp.status_code == 403
    assert "Secret body" not in resp.text


async def test_ac10_sweep_audits_expired_links_that_were_never_opened(
    client, owner_id, db_session, audit_events
):
    doc_id = await _create_document(client, owner_id)
    expired = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    await client.post(f"/api/v1/documents/{doc_id}/share")
    await _expire(db_session, expired["id"])

    assert await ShareLinkStore(db_session).sweep_expired() == 1
    assert await ShareLinkStore(db_session).sweep_expired() == 0
    expiries = [e for e in audit_events if e["action"] == "share_link_expire"]
    assert [e["resource_id"] for e in expiries] == [expired["id"]]


async def test_unknown_token_is_rejected(client, owner_id):
    doc_id = await _create_document(client, owner_id)
    resp = await client.get(
        "/api/v1/documents/shared",
        params={"document_id": doc_id, "token": "not-a-token"},
        auth=None,
    )
    assert resp.status_code == 403
