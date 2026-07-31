"""Tests for the SNS event publisher."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.event_publisher as mod
from app.services.event_publisher import EventPublisher, _UUIDEncoder


def test_uuid_encoder_serialises_uuids_and_datetimes():
    document_id = uuid.uuid4()
    moment = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    encoded = json.loads(json.dumps({"id": document_id, "at": moment}, cls=_UUIDEncoder))

    assert encoded == {"id": str(document_id), "at": moment.isoformat()}


def test_uuid_encoder_still_rejects_unsupported_types():
    with pytest.raises(TypeError):
        json.dumps({"value": object()}, cls=_UUIDEncoder)


def test_get_client_builds_a_regional_sns_client_once(monkeypatch):
    monkeypatch.setattr(mod.settings, "aws_region", "eu-west-1")
    monkeypatch.setattr(mod.settings, "aws_endpoint_url", "")
    factory = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("boto3.client", factory)
    publisher = EventPublisher()

    first = publisher._get_client()
    second = publisher._get_client()

    assert first is second
    factory.assert_called_once_with("sns", region_name="eu-west-1")


def test_get_client_honours_a_custom_endpoint_url(monkeypatch):
    monkeypatch.setattr(mod.settings, "aws_region", "us-east-1")
    monkeypatch.setattr(mod.settings, "aws_endpoint_url", "http://localstack:4566")
    factory = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("boto3.client", factory)

    EventPublisher()._get_client()

    factory.assert_called_once_with(
        "sns", region_name="us-east-1", endpoint_url="http://localstack:4566"
    )


@pytest.mark.asyncio
async def test_publish_is_skipped_when_sns_is_disabled(monkeypatch):
    monkeypatch.setattr(mod.settings, "sns_enabled", False)
    to_thread = AsyncMock()
    monkeypatch.setattr(mod.asyncio, "to_thread", to_thread)
    publisher = EventPublisher()
    publisher._client = MagicMock()

    await publisher.publish("document_created", {"id": "d-1"})

    to_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_sends_the_event_to_the_configured_topic(monkeypatch):
    monkeypatch.setattr(mod.settings, "sns_enabled", True)
    monkeypatch.setattr(mod.settings, "sns_topic_arn", "arn:aws:sns:::events")
    to_thread = AsyncMock()
    monkeypatch.setattr(mod.asyncio, "to_thread", to_thread)
    publisher = EventPublisher()
    client = MagicMock()
    publisher._client = client
    document_id = uuid.uuid4()

    await publisher.publish("document_created", {"id": document_id})

    call = to_thread.await_args
    assert call.args[0] is client.publish
    assert call.kwargs["TopicArn"] == "arn:aws:sns:::events"
    assert call.kwargs["MessageAttributes"] == {
        "event_type": {"DataType": "String", "StringValue": "document_created"}
    }
    message = json.loads(call.kwargs["Message"])
    assert message["event_type"] == "document_created"
    assert message["payload"] == {"id": str(document_id)}
    assert datetime.fromisoformat(message["timestamp"]).tzinfo is not None


@pytest.mark.asyncio
async def test_publish_swallows_sns_failures(monkeypatch):
    monkeypatch.setattr(mod.settings, "sns_enabled", True)
    to_thread = AsyncMock(side_effect=RuntimeError("sns down"))
    monkeypatch.setattr(mod.asyncio, "to_thread", to_thread)
    publisher = EventPublisher()
    publisher._client = MagicMock()

    assert await publisher.publish("document_deleted", {"id": "d-1"}) is None
    to_thread.assert_awaited_once()
