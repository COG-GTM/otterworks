"""OTW-53: expiring share links with workspace default and per-link override.

Test names reference the Given/When/Then acceptance criteria on OTW-53.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.models.sharing import ShareLink
from app.services.audit_client import AuditClient, audit_client
from app.services.share_link import ShareLinkService
from app.services.share_link_store import ShareLinkStore
from tests.conftest import TEST_JWT_SECRET


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture
def audit_events(monkeypatch):
    sink = RecordingSink()
    monkeypatch.setattr(audit_client, "sink", sink)
    return sink.events


def owner_headers(user_id: uuid.UUID) -> dict[str, str]:
    token = jwt.encode(
        {"user_id": str(user_id), "roles": ["ADMIN"]}, TEST_JWT_SECRET, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


async def make_doc(client) -> str:
    resp = await client.post("/api/v1/documents/", json={"title": "Doc", "content": "x"})
    assert resp.status_code == 201
    return resp.json()["id"]


async def set_policy(client, **policy):
    workspace_owner = uuid.uuid4()
    resp = await client.put(
        "/api/v1/documents/share-policy", json=policy, headers=owner_headers(workspace_owner)
    )
    assert resp.status_code == 200, resp.text
    return resp


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


@pytest.mark.asyncio
async def test_ac1_workspace_default_applied(client, audit_events):
    await set_policy(client, default_expiry_days=7, min_expiry_days=1, max_expiry_days=30)
    doc_id = await make_doc(client)

    resp = await client.post(f"/api/v1/documents/{doc_id}/share")

    assert resp.status_code == 200
    body = resp.json()
    delta = parse(body["expires_at"]) - parse(body["created_at"])
    assert delta == timedelta(days=7)


@pytest.mark.asyncio
async def test_ac2_override_within_bounds(client, audit_events):
    await set_policy(client, default_expiry_days=7, min_expiry_days=1, max_expiry_days=30)
    doc_id = await make_doc(client)

    created = await client.post(
        f"/api/v1/documents/{doc_id}/share", json={"expires_in_days": 14}
    )
    assert created.status_code == 200
    body = created.json()
    assert parse(body["expires_at"]) - parse(body["created_at"]) == timedelta(days=14)

    edited = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{body['link_id']}",
        json={"expires_in_days": 3},
    )
    assert edited.status_code == 200
    assert parse(edited.json()["expires_at"]) < parse(body["expires_at"])


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"expires_in_days": 90}, {"no_expiry": True}])
async def test_ac3_override_outside_bounds_rejected(client, db_session, audit_events, payload):
    await set_policy(
        client, default_expiry_days=7, min_expiry_days=1, max_expiry_days=30,
        allow_no_expiry=False,
    )
    doc_id = await make_doc(client)

    resp = await client.post(f"/api/v1/documents/{doc_id}/share", json=payload)

    assert resp.status_code == 422
    links = (await db_session.execute(select(ShareLink))).scalars().all()
    assert links == []


@pytest.mark.asyncio
async def test_ac3_edit_outside_bounds_leaves_link_unchanged(client, audit_events):
    await set_policy(client, default_expiry_days=7, min_expiry_days=1, max_expiry_days=30)
    doc_id = await make_doc(client)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()

    resp = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['link_id']}",
        json={"expires_in_days": 90},
    )

    assert resp.status_code == 422
    listed = (await client.get(f"/api/v1/documents/{doc_id}/share-links")).json()
    assert parse(listed[0]["expires_at"]) == parse(link["expires_at"])


@pytest.mark.asyncio
async def test_ac4_expired_link_returns_410_and_is_not_extended(
    client, db_session, audit_events
):
    await set_policy(client, default_expiry_days=1, min_expiry_days=1, max_expiry_days=30)
    doc_id = await make_doc(client)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()

    ok = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": link["token"]},
        auth=None,
    )
    assert ok.status_code == 200

    row = await db_session.get(ShareLink, uuid.UUID(link["link_id"]))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    gone = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": link["token"]},
        auth=None,
    )
    assert gone.status_code == 410

    assert [e["action"] for e in audit_events].count("share_link.expired") == 1

    extend = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['link_id']}",
        json={"expires_in_days": 30},
    )
    assert extend.status_code == 422


@pytest.mark.asyncio
async def test_ac5_only_workspace_owner_changes_policy(client, audit_events):
    resp = await client.put(
        "/api/v1/documents/share-policy",
        json={"default_expiry_days": 7, "min_expiry_days": 1, "max_expiry_days": 30},
    )
    assert resp.status_code == 403

    policy = await client.get("/api/v1/documents/share-policy")
    assert policy.status_code == 200
    assert policy.json()["default_expiry_days"] is None
    assert not [e for e in audit_events if e["action"] == "share_policy.changed"]


@pytest.mark.asyncio
async def test_ac5_policy_validation(client, audit_events):
    resp = await client.put(
        "/api/v1/documents/share-policy",
        json={"default_expiry_days": 60, "min_expiry_days": 1, "max_expiry_days": 30},
        headers=owner_headers(uuid.uuid4()),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ac6_legacy_links_are_not_retroactively_expired(client, audit_events):
    doc_id = await make_doc(client)
    legacy_token = ShareLinkService().mint_token(doc_id)
    await set_policy(
        client, default_expiry_days=1, min_expiry_days=1, max_expiry_days=1,
        allow_no_expiry=False,
    )

    resp = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": legacy_token},
        auth=None,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_ac6_policy_change_does_not_touch_existing_links(client, audit_events):
    doc_id = await make_doc(client)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    assert link["expires_at"] is None

    await set_policy(client, default_expiry_days=1, min_expiry_days=1, max_expiry_days=7)

    listed = (await client.get(f"/api/v1/documents/{doc_id}/share-links")).json()
    assert listed[0]["expires_at"] is None


@pytest.mark.asyncio
async def test_ac7_tokens_are_random_and_persisted(client, db_session, audit_events):
    doc_id = await make_doc(client)
    first = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    second = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()

    assert first["token"] != second["token"]
    assert first["token"] != ShareLinkService().mint_token(doc_id)
    assert len(first["token"]) >= 32
    query = select(ShareLink).where(ShareLink.token == first["token"])
    row = (await db_session.execute(query)).scalar_one()
    assert row.created_by is not None and row.created_at is not None


@pytest.mark.asyncio
async def test_ac8_audit_events_for_create_change_policy(client, audit_events, owner_id):
    await set_policy(client, default_expiry_days=7, min_expiry_days=1, max_expiry_days=30)
    doc_id = await make_doc(client)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['link_id']}",
        json={"expires_in_days": 14},
    )

    actions = [e["action"] for e in audit_events]
    assert actions == ["share_policy.changed", "share_link.created", "share_link.expiry_changed"]
    for event in audit_events:
        details = event["details"]
        assert {"workspace_id", "old_value", "new_value", "timestamp"} <= details.keys()
        assert event["userId"] and event["resourceId"]
    changed = audit_events[-1]
    assert changed["userId"] == str(owner_id)
    assert changed["details"]["old_value"] != changed["details"]["new_value"]


@pytest.mark.asyncio
async def test_ac8_expiry_emits_single_audit_event(db_session, owner_id):
    sink = RecordingSink()
    store = ShareLinkStore(db_session, audit=AuditClient(sink))
    from app.models.document import Document

    doc = Document(title="d", content="", owner_id=owner_id)
    db_session.add(doc)
    await db_session.commit()
    link = await store.create_link(doc.id, owner_id, expires_in_days=1)
    link.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    assert await store.sweep_expired() == 1
    assert await store.sweep_expired() == 0
    expired = [e for e in sink.events if e["action"] == "share_link.expired"]
    assert len(expired) == 1
    assert expired[0]["details"]["old_value"] == "active"
