"""OTW-69 folder share-link audit events (OTW-63 US5).

Tests are named after the Given/When/Then scenarios in OTW-69. Events are captured
at the SNS publisher boundary (``event_publisher.publish``), i.e. exactly what the
audit-service SnsConsumer receives, and validated against
shared/events/schemas/audit-events.json.
"""

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.folder_share_link import FolderShareLink
from app.services import event_publisher as event_publisher_module
from app.services.file_service_client import get_file_service_client
from app.services.folder_share_link_events import (
    ShareLinkEventType,
    build_share_link_event,
    emit_share_link_event,
    expiry_audit_id,
)
from app.services.folder_share_link_expiry_sweep import (
    run_expiry_sweep_loop,
    sweep_expired_links,
)
from app.services.folder_share_link_service import as_utc
from app.services.sharing_policy import get_sharing_policy_client
from tests.conftest import TestingSessionLocal
from tests.test_folder_share_links_api import (
    BASE,
    FakeFileService,
    FakePolicyClient,
    _create,
    _load,
    _ts,
    share_link_secret,  # noqa: F401  (autouse fixture)
)

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "shared/events/schemas/audit-events.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
EVENT_DEFINITIONS = {
    "folder_share_link.created": "FolderShareLinkCreatedEvent",
    "folder_share_link.updated": "FolderShareLinkUpdatedEvent",
    "folder_share_link.revoked": "FolderShareLinkRevokedEvent",
    "folder_share_link.expired": "FolderShareLinkExpiredEvent",
    "folder_share_link.policy_changed": "SharingPolicyChangedEvent",
}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
JSON_TYPES = {
    "object": dict, "string": str, "integer": int, "array": list, "null": type(None),
}


def _validate(instance: Any, schema: dict, path: str = "$") -> None:
    """Minimal JSON-schema check for the keywords the share-link definitions use."""
    if "$ref" in schema:
        schema = SCHEMA["definitions"][schema["$ref"].rsplit("/", 1)[-1]]
    if "const" in schema:
        assert instance == schema["const"], f"{path}: {instance!r} != {schema['const']!r}"
    if "enum" in schema:
        assert instance in schema["enum"], f"{path}: {instance!r} not in {schema['enum']}"
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        assert any(
            isinstance(instance, JSON_TYPES[t])
            and not (t == "integer" and isinstance(instance, bool))
            for t in types
        ), f"{path}: {instance!r} is not {types}"
    if isinstance(instance, str) and schema.get("format") == "uuid":
        assert UUID_RE.match(instance), f"{path}: {instance!r} is not a uuid"
    if isinstance(instance, str) and schema.get("format") == "date-time":
        assert datetime.fromisoformat(instance).tzinfo is not None, f"{path}: no offset"
    if isinstance(instance, int):
        assert schema.get("minimum", instance) <= instance <= schema.get("maximum", instance)
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            assert key in instance, f"{path}: missing {key}"
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                _validate(instance[key], sub, f"{path}.{key}")


def assert_matches_schema(event: dict) -> None:
    definition = SCHEMA["definitions"][EVENT_DEFINITIONS[event["eventType"]]]
    _validate(event, definition)


@pytest.fixture
async def api_client(client: AsyncClient, owner_id, folder_id) -> AsyncClient:
    file_service = FakeFileService()
    file_service.add_folder(folder_id, owner_id)
    app.dependency_overrides[get_file_service_client] = lambda: file_service
    app.dependency_overrides[get_sharing_policy_client] = lambda: FakePolicyClient()
    return client


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Capture what document-service publishes to SNS for the audit queue."""
    calls: list[tuple[str, dict]] = []

    async def publish(event_type: str, payload: dict) -> bool:
        calls.append((event_type, payload))
        return True

    monkeypatch.setattr(event_publisher_module.event_publisher, "publish", publish)
    return calls


def _link(**overrides: Any) -> FolderShareLink:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "folder_id": uuid.uuid4(),
        "workspace_id": "default",
        "token_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "created_by": uuid.uuid4(),
        "created_at": now - timedelta(days=2),
        "expires_at": now - timedelta(days=1),
    }
    values.update(overrides)
    return FolderShareLink(**values)


async def _insert(db: AsyncSession, *links: FolderShareLink) -> None:
    db.add_all(links)
    await db.commit()


async def _expiry_audited_at(db: AsyncSession, link_id: uuid.UUID) -> datetime | None:
    db.expire_all()
    return (
        await db.execute(
            select(FolderShareLink.expiry_audited_at).where(FolderShareLink.id == link_id)
        )
    ).scalar_one()


def _sweep_events(published: list[tuple[str, dict]]) -> list[dict]:
    return [p for t, p in published if t == ShareLinkEventType.EXPIRED]


# --- Schema ------------------------------------------------------------------------


def test_schema_defines_every_share_link_event_with_required_audit_fields():
    """Given the shared audit schema, Then created/updated/revoked/expired/policy_changed
    each require actor, workspace, resource, old value, new value and timestamp."""
    for event_type, name in EVENT_DEFINITIONS.items():
        definition = SCHEMA["definitions"][name]
        assert definition["properties"]["eventType"]["const"] == event_type
        assert {"actor", "workspaceId", "resource", "oldValue", "newValue", "timestamp"} <= set(
            definition["required"]
        )
    link_resource = SCHEMA["definitions"]["FolderShareLinkResource"]
    assert {"folderId", "linkId"} <= set(link_resource["required"])


# --- Link lifecycle via the API ----------------------------------------------------


async def test_given_link_created_when_create_succeeds_then_created_event_sent(
    api_client: AsyncClient, published, owner_id, folder_id
):
    """Given a folder link is created, Then an audit event is sent with actor, workspace,
    resource (folder id and link id), old value, new value and timestamp."""
    before = datetime.now(UTC)
    created = await _create(api_client, folder_id)

    assert len(published) == 1
    event_type, event = published[0]
    assert event_type == "folder_share_link.created"
    assert_matches_schema(event)
    assert event["actor"] == {"type": "user", "id": str(owner_id)}
    assert event["workspaceId"] == "default"
    assert event["resource"] == {
        "type": "folder_share_link", "folderId": str(folder_id), "linkId": created["id"],
    }
    assert event["oldValue"] is None
    assert _ts(event["newValue"]["expires_at"]) == _ts(created["expires_at"])
    assert datetime.fromisoformat(event["timestamp"]) >= before
    assert "token" not in json.dumps(event)


async def test_given_link_expiry_changed_when_patch_succeeds_then_updated_event_has_old_and_new(
    api_client: AsyncClient, published, owner_id, folder_id
):
    """Given a folder link is changed, Then an audit event carries the old and new expiry."""
    created = await _create(api_client, folder_id, expires_in_days=10)
    resp = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 20})
    assert resp.status_code == 200

    event_type, event = published[-1]
    assert event_type == "folder_share_link.updated"
    assert_matches_schema(event)
    assert event["actor"]["id"] == str(owner_id)
    assert _ts(event["oldValue"]["expires_at"]) == _ts(created["expires_at"])
    assert _ts(event["newValue"]["expires_at"]) == _ts(resp.json()["expires_at"])


async def test_given_patch_keeps_same_expiry_when_repeated_then_no_updated_event(
    api_client: AsyncClient, published, folder_id
):
    """Given a PATCH that does not change the expiry, Then no updated event is sent."""
    created = await _create(api_client, folder_id, expires_in_days=10)
    first = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 20})
    second = await api_client.patch(f"{BASE}/{created['id']}", json={"expires_in_days": 20})
    assert first.status_code == second.status_code == 200
    assert second.json()["expires_at"] == first.json()["expires_at"]
    assert [t for t, _ in published].count("folder_share_link.updated") == 1


async def test_given_link_revoked_when_delete_succeeds_then_revoked_event_sent(
    api_client: AsyncClient, published, owner_id, folder_id, db_session: AsyncSession
):
    """Given a folder link is revoked, Then an audit event records revoked_at old -> new."""
    created = await _create(api_client, folder_id)
    resp = await api_client.delete(f"{BASE}/{created['id']}")
    assert resp.status_code == 204

    event_type, event = published[-1]
    assert event_type == "folder_share_link.revoked"
    assert_matches_schema(event)
    assert event["resource"]["linkId"] == created["id"]
    assert event["oldValue"] == {"revoked_at": None}
    revoked_at = as_utc((await _load(db_session, created["id"])).revoked_at)
    assert datetime.fromisoformat(event["newValue"]["revoked_at"]) == revoked_at


async def test_given_rejected_request_then_no_audit_event_sent(
    api_client: AsyncClient, published, folder_id
):
    """Given a change is rejected (out of bounds or already revoked), Then nothing is sent."""
    created = await _create(api_client, folder_id)
    assert (await api_client.patch(f"{BASE}/{created['id']}",
                                   json={"expires_in_days": 91})).status_code == 422
    assert (await api_client.delete(f"{BASE}/{created['id']}")).status_code == 204
    assert (await api_client.patch(f"{BASE}/{created['id']}",
                                   json={"expires_in_days": 5})).status_code == 409
    assert [t for t, _ in published] == [
        "folder_share_link.created", "folder_share_link.revoked",
    ]


async def test_given_audit_delivery_fails_when_link_created_then_request_still_succeeds(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, folder_id
):
    """Given SNS is unavailable, When a link is created, Then the API still returns 201."""

    async def broken(*_args, **_kwargs):
        raise RuntimeError("sns down")

    monkeypatch.setattr(event_publisher_module.event_publisher, "publish", broken)
    await _create(api_client, folder_id)


# --- Expiry sweep ------------------------------------------------------------------


async def test_given_link_expires_when_sweep_runs_twice_then_exactly_one_system_event(
    db_session: AsyncSession, published
):
    """Given a folder link expires, When the scheduled sweep runs (repeatedly), Then exactly
    one expiry event is sent with actor = system and expiry_audited_at is set."""
    link = _link()
    await _insert(db_session, link)

    assert await sweep_expired_links(db_session) == 1
    assert await sweep_expired_links(db_session) == 0

    events = _sweep_events(published)
    assert len(events) == 1
    event = events[0]
    assert_matches_schema(event)
    assert event["actor"] == {"type": "system", "id": None}
    assert event["workspaceId"] == "default"
    assert event["resource"] == {
        "type": "folder_share_link", "folderId": str(link.folder_id), "linkId": str(link.id),
    }
    expires_at = as_utc(link.expires_at).isoformat()
    assert event["oldValue"] == {"status": "active", "expires_at": expires_at}
    assert event["newValue"] == {"status": "expired", "expires_at": expires_at}
    assert event["timestamp"] == expires_at
    assert event["auditId"] == str(expiry_audit_id(link.id))
    assert await _expiry_audited_at(db_session, link.id) is not None


async def test_given_active_or_already_audited_links_when_sweep_runs_then_no_event(
    db_session: AsyncSession, published
):
    """Given links that have not expired or were already audited, Then the sweep skips them."""
    now = datetime.now(UTC)
    await _insert(
        db_session,
        _link(expires_at=now + timedelta(days=1)),
        _link(expiry_audited_at=now - timedelta(hours=1)),
    )
    assert await sweep_expired_links(db_session) == 0
    assert published == []


async def test_given_link_revoked_before_expiry_when_sweep_runs_then_no_expiry_event(
    db_session: AsyncSession, published
):
    """Given a link was revoked before it expired, Then no expiry event is sent (its revocation
    is the terminal event); a link revoked after it expired still gets one expiry event."""
    now = datetime.now(UTC)
    revoked_first = _link(revoked_at=now - timedelta(days=1, hours=1))
    expired_first = _link(revoked_at=now - timedelta(hours=1))
    await _insert(db_session, revoked_first, expired_first)

    assert await sweep_expired_links(db_session) == 1
    assert [e["resource"]["linkId"] for e in _sweep_events(published)] == [str(expired_first.id)]


async def test_given_publish_fails_when_sweep_runs_then_link_is_retried_next_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Given SNS delivery fails, Then expiry_audited_at stays null and the next sweep emits
    the event once delivery succeeds (still exactly one delivered event)."""
    link = _link()
    await _insert(db_session, link)
    delivered: list[dict] = []
    healthy = False

    async def publish(event_type: str, payload: dict) -> bool:
        if healthy:
            delivered.append(payload)
        return healthy

    monkeypatch.setattr(event_publisher_module.event_publisher, "publish", publish)
    assert await sweep_expired_links(db_session) == 0
    assert await _expiry_audited_at(db_session, link.id) is None

    healthy = True
    assert await sweep_expired_links(db_session) == 1
    assert await sweep_expired_links(db_session) == 0
    assert len(delivered) == 1


async def test_given_more_expired_links_than_batch_when_sweep_runs_then_all_emitted_once(
    db_session: AsyncSession, published
):
    """Given more expired links than one batch, Then one sweep emits one event per link."""
    links = [_link() for _ in range(5)]
    await _insert(db_session, *links)

    assert await sweep_expired_links(db_session, batch_size=2) == 5
    assert sorted(e["resource"]["linkId"] for e in _sweep_events(published)) == sorted(
        str(link.id) for link in links
    )


async def test_given_scheduler_running_when_interval_elapses_then_sweep_emits(
    db_session: AsyncSession, published
):
    """Given the scheduled loop is running, When a link has expired, Then it is swept
    without a request, and the loop stops cleanly on cancel."""
    await _insert(db_session, _link())
    task = asyncio.create_task(run_expiry_sweep_loop(TestingSessionLocal, 0.01))
    for _ in range(100):
        if _sweep_events(published):
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(_sweep_events(published)) == 1


# --- Event builder -----------------------------------------------------------------


async def test_emit_never_raises_and_reports_failure(monkeypatch: pytest.MonkeyPatch):
    """Given the publisher raises, Then emit_share_link_event returns False instead of raising."""

    async def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(event_publisher_module.event_publisher, "publish", broken)
    assert await emit_share_link_event(ShareLinkEventType.CREATED, _link(), uuid.uuid4()) is False


async def test_given_sns_disabled_when_publishing_then_not_reported_as_delivered(
    monkeypatch: pytest.MonkeyPatch,
):
    """Given SNS publishing is disabled, Then publish reports not delivered, so the expiry
    sweep leaves expiry_audited_at null and the event is sent once SNS is enabled."""
    monkeypatch.setattr(event_publisher_module.settings, "sns_enabled", False)
    publisher = event_publisher_module.EventPublisher()
    assert await publisher.publish("folder_share_link.expired", {}) is False


def test_built_events_match_schema_for_every_link_event_type():
    link = _link()
    actor = uuid.uuid4()
    expiry = {"expires_at": as_utc(link.expires_at).isoformat()}
    status = {"status": "active", **expiry}
    for event_type, old, new in [
        (ShareLinkEventType.CREATED, None, expiry),
        (ShareLinkEventType.EXPIRY_UPDATED, expiry, expiry),
        (ShareLinkEventType.REVOKED, {"revoked_at": None}, {"revoked_at": expiry["expires_at"]}),
    ]:
        assert_matches_schema(build_share_link_event(event_type, link, actor, old, new))
    assert_matches_schema(
        build_share_link_event(ShareLinkEventType.EXPIRED, link, None, status, status)
    )
