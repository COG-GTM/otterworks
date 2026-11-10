"""Audit events for folder share links and the workspace share policy (OTW-46, parent OTW-41).

Each test names the OTW-46 Given/When/Then scenario it covers.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.main import app
from app.models.share_link import ShareLink
from app.services import event_publisher as event_publisher_module
from app.services.event_publisher import EventPublisher, event_publisher
from app.services.file_service_client import get_file_service_client
from app.services.share_link_expiry_sweep import (
    run_expiry_sweep_loop,
    sweep_expired_share_links,
)
from app.services.share_link_repository import EffectiveSharePolicy, ShareLinkRepository
from app.services.share_policy_events import emit_policy_changed_event
from tests.conftest import TEST_JWT_SECRET, TestingSessionLocal
from tests.test_share_links_api import FakeFileService

SHARE_LINKS = "/api/v1/share-links"
POLICY = "/api/v1/workspace/share-policy"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "shared/events/schemas/audit-events.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

# Payload keys audit-service's SnsConsumer.MapAuditEventMessage reads (AuditEventMessage's
# snake_case JsonPropertyName / case-insensitive properties, OTW-47 / PR #631).
CONSUMER_PAYLOAD_KEYS = {
    "user_id",
    "actor_id",
    "action",
    "event_type",
    "resource_type",
    "resource_id",
    "workspace_id",
    "old_value",
    "new_value",
    "timestamp",
    "details",
    "ip_address",
    "user_agent",
}
PUBLISHED_PAYLOAD_KEYS = {
    "user_id",
    "action",
    "resource_type",
    "resource_id",
    "workspace_id",
    "old_value",
    "new_value",
    "timestamp",
    "details",
}
EVENT_DEFINITIONS = {
    "share_link_created": "ShareLinkCreatedEvent",
    "share_link_expiry_changed": "ShareLinkExpiryChangedEvent",
    "share_link_expired": "ShareLinkExpiredEvent",
    "workspace_share_policy_changed": "WorkspaceSharePolicyChangedEvent",
}


# -- helpers ---------------------------------------------------------------------------


_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "null": type(None),
}


def _validate(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Minimal draft-07 validator for the keywords used by audit-events.json."""
    if "$ref" in schema:
        _validate(instance, SCHEMA["definitions"][schema["$ref"].rsplit("/", 1)[-1]], path)
    for sub in schema.get("allOf", []):
        _validate(instance, sub, path)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        assert any(isinstance(instance, _JSON_TYPES[t]) for t in types), f"{path}: type"
    if "const" in schema:
        assert instance == schema["const"], f"{path}: {instance!r} != {schema['const']!r}"
    if "enum" in schema:
        assert instance in schema["enum"], f"{path}: {instance!r} not in enum"
    if schema.get("format") == "date-time":
        datetime.fromisoformat(instance)
    if "minimum" in schema:
        assert instance >= schema["minimum"], path
    if "maximum" in schema:
        assert instance <= schema["maximum"], path
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            assert key in instance, f"{path}: missing {key}"
        props = schema.get("properties", {})
        for key, value in instance.items():
            if key in props:
                _validate(value, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise AssertionError(f"{path}: unexpected key {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate(value, schema["additionalProperties"], f"{path}.{key}")


def _assert_valid_audit_message(message: dict[str, Any]) -> None:
    definition = SCHEMA["definitions"][EVENT_DEFINITIONS[message["event_type"]]]
    _validate(message, definition)
    assert set(message["payload"]) == PUBLISHED_PAYLOAD_KEYS
    assert set(message["payload"]) <= CONSUMER_PAYLOAD_KEYS


class FakeSns:
    """Captures what EventPublisher sends to SNS (the real wire format)."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.fail = False

    def publish(self, **kwargs: Any) -> dict[str, str]:
        if self.fail:
            raise RuntimeError("SNS unavailable")
        self.messages.append(json.loads(kwargs["Message"]))
        return {"MessageId": "m-1"}

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["event_type"] == event_type]


@pytest.fixture
def sns(monkeypatch) -> FakeSns:
    fake = FakeSns()
    monkeypatch.setattr(event_publisher_module.settings, "sns_enabled", True)
    monkeypatch.setattr(event_publisher, "_client", fake)
    return fake


@pytest.fixture
def files(client: AsyncClient, owner_id: uuid.UUID, folder_id: uuid.UUID) -> FakeFileService:
    fake = FakeFileService()
    fake.add_folder(folder_id, owner_id, files=1)
    app.dependency_overrides[get_file_service_client] = lambda: fake
    return fake


def _owner_headers(user_id: uuid.UUID, workspace_id: str = "ws-audit") -> dict[str, str]:
    claims = {"user_id": str(user_id), "roles": ["OWNER"], "workspace_id": workspace_id}
    return {"Authorization": f"Bearer {jwt.encode(claims, TEST_JWT_SECRET, algorithm='HS256')}"}


async def _create(client: AsyncClient, folder_id: uuid.UUID, **body: Any) -> dict[str, Any]:
    resp = await client.post(
        SHARE_LINKS, json={"resource_type": "folder", "resource_id": str(folder_id), **body}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _expire(db: AsyncSession, link_id: str) -> datetime:
    link = await db.get(ShareLink, uuid.UUID(link_id))
    link.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await db.commit()
    return link.expires_at


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _recent(value: str) -> bool:
    return abs((datetime.now(UTC) - _ts(value)).total_seconds()) < 60


# -- Scenario 1: Given a folder link is created, Then share_link_created is published with
# actor, workspace, resource, old=null, new={"expires_at"} and timestamp.


async def test_create_publishes_share_link_created(client, files, folder_id, owner_id, sns):
    created = await _create(client, folder_id, expires_in_days=7)

    [message] = sns.of_type("share_link_created")
    _assert_valid_audit_message(message)
    assert message["payload"] == {
        "user_id": str(owner_id),
        "action": "share_link_created",
        "resource_type": "folder",
        "resource_id": str(folder_id),
        "workspace_id": "default",
        "old_value": None,
        "new_value": {"expires_at": message["payload"]["new_value"]["expires_at"]},
        "timestamp": message["payload"]["timestamp"],
        "details": {"share_link_id": created["id"]},
    }
    assert _ts(message["payload"]["new_value"]["expires_at"]) == _ts(created["expires_at"])
    assert _recent(message["payload"]["timestamp"])


async def test_create_records_callers_workspace(client, files, folder_id, owner_id, sns):
    resp = await client.post(
        SHARE_LINKS,
        json={"resource_type": "folder", "resource_id": str(folder_id)},
        headers=_owner_headers(owner_id, "ws-42"),
    )
    assert resp.status_code == 201

    [message] = sns.of_type("share_link_created")
    assert message["payload"]["workspace_id"] == "ws-42"


# -- Scenario 2: Given a link's expiry is changed, Then share_link_expiry_changed carries
# old={"expires_at": old} and new={"expires_at": new}.


async def test_patch_publishes_expiry_changed_with_old_and_new(
    client, files, folder_id, owner_id, sns
):
    created = await _create(client, folder_id, expires_in_days=30)
    resp = await client.patch(f"{SHARE_LINKS}/{created['id']}", json={"expires_in_days": 3})
    assert resp.status_code == 200

    [message] = sns.of_type("share_link_expiry_changed")
    _assert_valid_audit_message(message)
    payload = message["payload"]
    assert payload["user_id"] == str(owner_id)
    assert (payload["resource_type"], payload["resource_id"]) == ("folder", str(folder_id))
    assert _ts(payload["old_value"]["expires_at"]) == _ts(created["expires_at"])
    assert _ts(payload["new_value"]["expires_at"]) == _ts(resp.json()["expires_at"])
    assert payload["details"] == {"share_link_id": created["id"]}


async def test_rejected_patch_publishes_nothing(client, files, folder_id, sns):
    created = await _create(client, folder_id)
    resp = await client.patch(f"{SHARE_LINKS}/{created['id']}", json={"expires_in_days": 91})
    assert resp.status_code == 422

    assert sns.of_type("share_link_expiry_changed") == []


# -- Scenario 3: Given a link expires, Then share_link_expired is emitted exactly once with
# actor "system", old={"expires_at"} and new={"expired_at"}: on first resolve...


async def test_resolve_publishes_share_link_expired_once(client, files, folder_id, db_session, sns):
    created = await _create(client, folder_id)
    expires_at = await _expire(db_session, created["id"])

    first = await client.get(f"{SHARE_LINKS}/resolve/{created['token']}", auth=None)
    second = await client.get(f"{SHARE_LINKS}/resolve/{created['token']}", auth=None)
    assert (first.status_code, second.status_code) == (410, 410)

    [message] = sns.of_type("share_link_expired")
    _assert_valid_audit_message(message)
    payload = message["payload"]
    assert payload["user_id"] == "system"
    assert payload["workspace_id"] == "default"
    assert (payload["resource_type"], payload["resource_id"]) == ("folder", str(folder_id))
    assert _ts(payload["old_value"]["expires_at"]) == expires_at
    assert _ts(payload["new_value"]["expired_at"]) == _ts(first.json()["expired_at"])


# ...and from the periodic sweep, which never extends expiry.


async def test_sweep_marks_past_expiry_links_and_publishes_once(
    client, files, folder_id, db_session, sns
):
    expired = await _create(client, folder_id)
    live = await _create(client, folder_id)
    expires_at = await _expire(db_session, expired["id"])

    async with TestingSessionLocal() as sweep_db:
        assert await sweep_expired_share_links(sweep_db) == 1
    async with TestingSessionLocal() as sweep_db:
        assert await sweep_expired_share_links(sweep_db) == 0

    [message] = sns.of_type("share_link_expired")
    _assert_valid_audit_message(message)
    assert message["payload"]["user_id"] == "system"
    assert message["payload"]["details"] == {"share_link_id": expired["id"]}

    db_session.expire_all()
    marked = await db_session.get(ShareLink, uuid.UUID(expired["id"]))
    untouched = await db_session.get(ShareLink, uuid.UUID(live["id"]))
    assert marked.expired_at is not None
    assert marked.expires_at.replace(tzinfo=UTC) == expires_at
    assert untouched.expired_at is None
    assert _ts(message["payload"]["new_value"]["expired_at"]) == marked.expired_at.replace(
        tzinfo=UTC
    )


async def test_resolve_after_sweep_does_not_publish_again(
    client, files, folder_id, db_session, sns
):
    created = await _create(client, folder_id)
    await _expire(db_session, created["id"])

    async with TestingSessionLocal() as sweep_db:
        await sweep_expired_share_links(sweep_db)
    resp = await client.get(f"{SHARE_LINKS}/resolve/{created['token']}", auth=None)

    assert resp.status_code == 410
    assert resp.json()["expired_at"] is not None
    assert len(sns.of_type("share_link_expired")) == 1


async def test_sweep_after_resolve_does_not_publish_again(
    client, files, folder_id, db_session, sns
):
    created = await _create(client, folder_id)
    await _expire(db_session, created["id"])

    await client.get(f"{SHARE_LINKS}/resolve/{created['token']}", auth=None)
    async with TestingSessionLocal() as sweep_db:
        assert await sweep_expired_share_links(sweep_db) == 0

    assert len(sns.of_type("share_link_expired")) == 1


async def test_sweep_skips_link_another_worker_already_marked(db_session, sns, owner_id):
    repo = ShareLinkRepository(db_session)
    link = await repo.create(
        resource_id=uuid.uuid4(),
        workspace_id="default",
        created_by=owner_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    async with TestingSessionLocal() as other:
        stale = await ShareLinkRepository(other).get(link.id)
        assert await ShareLinkRepository(other).mark_expired(stale, datetime.now(UTC))

    async with TestingSessionLocal() as sweep_db:
        assert await sweep_expired_share_links(sweep_db) == 0
    assert sns.of_type("share_link_expired") == []


def test_sweep_is_on_by_default_every_five_minutes():
    defaults = Settings()
    assert defaults.share_link_expiry_sweep_enabled is True
    assert defaults.share_link_expiry_sweep_interval_seconds == 300


async def test_sweep_loop_keeps_running_after_a_failed_run(monkeypatch):
    calls: list[int] = []

    async def _flaky(_db):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db down")
        return 0

    monkeypatch.setattr("app.services.share_link_expiry_sweep.sweep_expired_share_links", _flaky)
    task = asyncio.create_task(run_expiry_sweep_loop(TestingSessionLocal, 0.01))
    for _ in range(100):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 2


async def test_lifespan_starts_and_stops_sweep_only_when_enabled(monkeypatch):
    from app import main

    started: list[float] = []

    async def _loop(_factory, interval):
        started.append(interval)
        await asyncio.Event().wait()

    async def _noop() -> None:
        return None

    monkeypatch.setattr(main, "run_expiry_sweep_loop", _loop)
    monkeypatch.setattr(main, "init_db", _noop)
    monkeypatch.setattr(main.engine, "dispose", _noop)

    monkeypatch.setattr(main.settings, "share_link_expiry_sweep_interval_seconds", 42.0)
    async with main.lifespan(app):
        await asyncio.sleep(0)
    assert started == [42.0]

    monkeypatch.setattr(main.settings, "share_link_expiry_sweep_enabled", False)
    async with main.lifespan(app):
        await asyncio.sleep(0)
    assert started == [42.0]


# -- Scenario 4: Given the workspace share policy changes, Then an audit event records the
# old and new default_days and max_days.


async def test_policy_change_publishes_old_and_new_days(client, owner_id, sns):
    headers = _owner_headers(owner_id)
    first = await client.put(POLICY, json={"default_days": 7, "max_days": 14}, headers=headers)
    second = await client.put(POLICY, json={"default_days": 10, "max_days": 60}, headers=headers)
    assert (first.status_code, second.status_code) == (200, 200)

    messages = sns.of_type("workspace_share_policy_changed")
    assert len(messages) == 2
    for message in messages:
        _assert_valid_audit_message(message)
    assert messages[0]["payload"] == {
        "user_id": str(owner_id),
        "action": "workspace_share_policy_changed",
        "resource_type": "workspace",
        "resource_id": "ws-audit",
        "workspace_id": "ws-audit",
        "old_value": {"default_days": 30, "max_days": 90},
        "new_value": {"default_days": 7, "max_days": 14},
        "timestamp": messages[0]["payload"]["timestamp"],
        "details": {},
    }
    assert _ts(messages[0]["payload"]["timestamp"]) == _ts(first.json()["updated_at"])
    assert messages[1]["payload"]["old_value"] == {"default_days": 7, "max_days": 14}
    assert messages[1]["payload"]["new_value"] == {"default_days": 10, "max_days": 60}


async def test_rejected_policy_change_publishes_nothing(client, owner_id, sns):
    resp = await client.put(
        POLICY, json={"default_days": 60, "max_days": 30}, headers=_owner_headers(owner_id)
    )
    assert resp.status_code == 422
    assert sns.messages == []


# -- Scenario 5: Publishing failures must not fail the user's request.


async def test_sns_failure_does_not_fail_create_patch_or_policy(
    client, files, folder_id, owner_id, sns
):
    sns.fail = True

    created = await _create(client, folder_id)
    patched = await client.patch(f"{SHARE_LINKS}/{created['id']}", json={"expires_in_days": 2})
    policy = await client.put(
        POLICY, json={"default_days": 5, "max_days": 10}, headers=_owner_headers(owner_id)
    )

    assert (patched.status_code, policy.status_code) == (200, 200)


async def test_unexpected_publisher_error_does_not_fail_resolve(
    client, files, folder_id, db_session, monkeypatch
):
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("publisher bug")

    monkeypatch.setattr(event_publisher, "publish", _boom)
    created = await _create(client, folder_id)
    await _expire(db_session, created["id"])

    resp = await client.get(f"{SHARE_LINKS}/resolve/{created['token']}", auth=None)
    assert resp.status_code == 410


# -- Contract with audit-service (PR #631): the wire message is the EventPublisher envelope
# and every payload key is one SnsConsumer.MapAuditEventMessage reads.


async def test_wire_message_matches_audit_consumer_contract(monkeypatch):
    fake = FakeSns()
    publisher = EventPublisher()
    publisher._client = fake
    monkeypatch.setattr(event_publisher_module.settings, "sns_enabled", True)
    monkeypatch.setattr("app.services.audit_events.event_publisher", publisher)

    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    await emit_policy_changed_event(
        EffectiveSharePolicy.builtin("ws-42"),
        EffectiveSharePolicy("ws-42", 7, 14, updated_at=now),
        actor_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        workspace_id="ws-42",
    )

    [message] = fake.messages
    assert set(message) == {"event_type", "timestamp", "payload"}
    _assert_valid_audit_message(message)
    assert message["payload"]["action"] == message["event_type"]
    assert message["payload"]["timestamp"] == "2026-11-03T12:00:00+00:00"


def test_schema_defines_the_four_share_events():
    for event_type, name in EVENT_DEFINITIONS.items():
        definition = SCHEMA["definitions"][name]
        assert definition["properties"]["event_type"]["const"] == event_type
    payload = SCHEMA["definitions"]["ShareAuditPayload"]
    assert set(payload["properties"]) == PUBLISHED_PAYLOAD_KEYS
    assert set(payload["properties"]) <= CONSUMER_PAYLOAD_KEYS
