"""Expiring share links with workspace default and per-link override (OTW-74).

Test names reference the acceptance criteria on OTW-74.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.models.share_link import ShareLink
from app.services import expiring_share_links as esl
from app.services.audit_client import AuditDeliveryError
from app.services.share_link import ShareLinkService
from tests.conftest import TEST_JWT_SECRET


def _auth(user_id: uuid.UUID, roles: list[str] | None = None, workspace: str | None = None):
    claims: dict = {"user_id": str(user_id)}
    if roles is not None:
        claims["roles"] = roles
    if workspace:
        claims["workspace_id"] = workspace
    return {"Authorization": f"Bearer {jwt.encode(claims, TEST_JWT_SECRET, algorithm='HS256')}"}


@pytest.fixture
def audit_events(monkeypatch):
    events: list[dict] = []

    async def _record(**event):
        events.append(event)

    monkeypatch.setattr(esl.audit_client, "record", _record)
    return events


@pytest.fixture
async def doc_id(client, owner_id) -> str:
    created = await client.post(
        "/api/v1/documents/", json={"title": "Shared", "content": "body", "owner_id": str(owner_id)}
    )
    return created.json()["id"]


async def _set_policy(client, owner_id, default=7, minimum=1, maximum=30):
    return await client.put(
        "/api/v1/documents/share-policy",
        json={
            "default_expiry_days": default,
            "min_expiry_days": minimum,
            "max_expiry_days": maximum,
        },
        headers=_auth(owner_id, roles=["ADMIN"]),
    )


def _days_between(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 86400


@pytest.mark.asyncio
async def test_ac1_workspace_default_applied(client, owner_id, doc_id, audit_events):
    assert (await _set_policy(client, owner_id, default=7)).status_code == 200
    minted = await client.post(f"/api/v1/documents/{doc_id}/share")
    assert minted.status_code == 200
    body = minted.json()
    assert round(_days_between(body["created_at"], body["expires_at"])) == 7
    assert body["created_by"] == str(owner_id)
    listed = await client.get(f"/api/v1/documents/{doc_id}/share-links")
    assert [link["id"] for link in listed.json()] == [body["id"]]


@pytest.mark.asyncio
async def test_ac1_built_in_default_when_no_policy_saved(client, doc_id, audit_events):
    policy = (await client.get("/api/v1/documents/share-policy")).json()
    assert policy["workspace_id"] == "default"
    minted = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    assert (
        round(_days_between(minted["created_at"], minted["expires_at"]))
        == policy["default_expiry_days"]
    )


@pytest.mark.asyncio
async def test_ac2_per_link_override_within_bounds(client, owner_id, doc_id, audit_events):
    await _set_policy(client, owner_id, default=7, minimum=1, maximum=30)
    minted = await client.post(f"/api/v1/documents/{doc_id}/share", json={"expires_in_days": 14})
    assert minted.status_code == 200
    assert round(_days_between(minted.json()["created_at"], minted.json()["expires_at"])) == 14

    edited = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{minted.json()['id']}", json={"expires_in_days": 3}
    )
    assert edited.status_code == 200
    remaining = datetime.fromisoformat(edited.json()["expires_at"]) - datetime.now(UTC)
    assert timedelta(days=2, hours=23) < remaining <= timedelta(days=3)


@pytest.mark.asyncio
async def test_ac3_override_outside_bounds_rejected(
    client, owner_id, doc_id, db_session, audit_events
):
    await _set_policy(client, owner_id, maximum=30)
    rejected = await client.post(f"/api/v1/documents/{doc_id}/share", json={"expires_in_days": 90})
    assert rejected.status_code == 422
    assert "between 1 and 30" in rejected.json()["detail"]
    assert (await db_session.execute(select(ShareLink))).scalars().all() == []

    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    edited = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['id']}", json={"expires_in_days": 90}
    )
    assert edited.status_code == 422
    unchanged = (await client.get(f"/api/v1/documents/{doc_id}/share-links")).json()[0]
    assert unchanged["expires_at"] == link["expires_at"]


@pytest.mark.asyncio
async def test_ac4_expired_link_returns_410_and_is_not_extended(
    client, doc_id, db_session, audit_events
):
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    row = await db_session.get(ShareLink, uuid.UUID(link["id"]))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    opened = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": link["token"]}
    )
    assert opened.status_code == 410
    assert opened.json()["detail"] == "This share link has expired"

    extended = await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['id']}", json={"expires_in_days": 7}
    )
    assert extended.status_code == 410
    again = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": link["token"]}
    )
    assert again.status_code == 410


@pytest.mark.asyncio
async def test_ac5_valid_link_returns_document(client, doc_id, audit_events):
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    opened = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": link["token"]}
    )
    assert opened.status_code == 200
    assert opened.json()["id"] == doc_id
    wrong = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": link["token"] + "x"}
    )
    assert wrong.status_code == 403


@pytest.mark.asyncio
async def test_ac6_tokens_are_random_and_persisted(client, doc_id, db_session, audit_events):
    first = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    second = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    assert first["token"] != second["token"]
    assert len(first["token"]) >= 32
    assert first["token"] != ShareLinkService().mint_token(doc_id)
    row = await db_session.get(ShareLink, uuid.UUID(first["id"]))
    assert row.token == first["token"] and row.created_by and row.expires_at


@pytest.mark.asyncio
async def test_ac7_legacy_links_are_not_retroactively_expired(
    client, owner_id, doc_id, audit_events
):
    legacy_token = ShareLinkService().mint_token(doc_id)
    await _set_policy(client, owner_id, default=1, minimum=1, maximum=2)
    opened = await client.get(
        "/api/v1/documents/shared", params={"document_id": doc_id, "token": legacy_token}
    )
    assert opened.status_code == 200


@pytest.mark.asyncio
async def test_ac8_every_change_is_audited(client, owner_id, doc_id, db_session, audit_events):
    await _set_policy(client, owner_id, default=7, minimum=1, maximum=30)
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    await client.patch(
        f"/api/v1/documents/{doc_id}/share-links/{link['id']}", json={"expires_in_days": 2}
    )
    row = await db_session.get(ShareLink, uuid.UUID(link["id"]))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()
    params = {"document_id": doc_id, "token": link["token"]}
    await client.get("/api/v1/documents/shared", params=params)
    await client.get("/api/v1/documents/shared", params=params)

    actions = [e["action"] for e in audit_events]
    assert actions == [
        "share_policy.updated",
        "share_link.created",
        "share_link.expiry_changed",
        "share_link.expired",
    ]
    for event in audit_events:
        assert event["actor_id"] == str(owner_id)
        assert event["workspace_id"] == "default"
        assert event["resource_id"]
    changed = audit_events[2]
    assert changed["old_value"] == link["expires_at"] and changed["new_value"] != link["expires_at"]
    assert audit_events[0]["old_value"] == "default=7d,min=1d,max=30d"


@pytest.mark.asyncio
async def test_ac8_no_change_saved_without_audit(client, doc_id, db_session, monkeypatch):
    async def _fail(**_event):
        raise AuditDeliveryError("down")

    monkeypatch.setattr(esl.audit_client, "record", _fail)
    failed = await client.post(f"/api/v1/documents/{doc_id}/share")
    assert failed.status_code == 503
    assert (await db_session.execute(select(ShareLink))).scalars().all() == []


@pytest.mark.asyncio
async def test_policy_requires_workspace_owner_and_valid_bounds(client, owner_id, audit_events):
    forbidden = await client.put(
        "/api/v1/documents/share-policy",
        json={"default_expiry_days": 7, "min_expiry_days": 1, "max_expiry_days": 30},
        headers=_auth(owner_id, roles=["USER"]),
    )
    assert forbidden.status_code == 403
    invalid = await _set_policy(client, owner_id, default=40, minimum=1, maximum=30)
    assert invalid.status_code == 422
    assert audit_events == []


@pytest.mark.asyncio
async def test_policy_is_scoped_per_workspace(client, owner_id, audit_events):
    await client.put(
        "/api/v1/documents/share-policy",
        json={"default_expiry_days": 3, "min_expiry_days": 1, "max_expiry_days": 5},
        headers=_auth(owner_id, roles=["ADMIN"], workspace="acme"),
    )
    acme = await client.get(
        "/api/v1/documents/share-policy", headers=_auth(owner_id, workspace="acme")
    )
    other = await client.get(
        "/api/v1/documents/share-policy", headers=_auth(owner_id, workspace="beta")
    )
    assert acme.json()["default_expiry_days"] == 3
    assert other.json()["default_expiry_days"] == 7


@pytest.mark.asyncio
async def test_ac8_expiry_recorded_once_even_with_stale_reads(
    client, doc_id, db_session, audit_events
):
    link = (await client.post(f"/api/v1/documents/{doc_id}/share")).json()
    row = await db_session.get(ShareLink, uuid.UUID(link["id"]))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    service = esl.ExpiringShareLinkService(db_session)
    # Two readers that both loaded the link before either recorded the expiry.
    stale = await service.find_by_token(uuid.UUID(doc_id), link["token"])
    db_session.expunge(stale)
    await service.record_expired(stale)
    assert stale.expired_recorded_at is None
    await service.record_expired(stale)

    assert [e["action"] for e in audit_events].count("share_link.expired") == 1
