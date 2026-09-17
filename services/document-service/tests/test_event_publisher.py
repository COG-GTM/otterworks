"""Tests for the SNS event publisher."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

import app.services.event_publisher as mod
from app.services.event_publisher import EventPublisher, _UUIDEncoder


@pytest.fixture
def sns_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod.settings, "sns_enabled", True)
    monkeypatch.setattr(mod.settings, "sns_topic_arn", "arn:aws:sns:us-east-1:000:events")


# ---- _UUIDEncoder ----


def test_uuid_encoder_serialises_uuid_and_datetime():
    doc_id = uuid.uuid4()
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    encoded = json.loads(json.dumps({"id": doc_id, "at": moment}, cls=_UUIDEncoder))

    assert encoded == {"id": str(doc_id), "at": moment.isoformat()}


def test_uuid_encoder_defers_unknown_types_to_the_base_encoder():
    with pytest.raises(TypeError):
        json.dumps({"blob": object()}, cls=_UUIDEncoder)


# ---- _get_client ----


def test_get_client_is_created_once_without_an_endpoint_override(monkeypatch):
    monkeypatch.setattr(mod.settings, "aws_endpoint_url", "")
    monkeypatch.setattr(mod.settings, "aws_region", "eu-west-1")
    boto3 = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "boto3", boto3)
    publisher = EventPublisher()

    first = publisher._get_client()
    second = publisher._get_client()

    assert first is second
    boto3.client.assert_called_once_with("sns", region_name="eu-west-1")


def test_get_client_uses_the_configured_endpoint_url(monkeypatch):
    monkeypatch.setattr(mod.settings, "aws_endpoint_url", "http://localstack:4566")
    boto3 = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "boto3", boto3)

    EventPublisher()._get_client()

    assert boto3.client.call_args.kwargs["endpoint_url"] == "http://localstack:4566"


# ---- publish ----


async def test_publish_is_skipped_when_sns_is_disabled(monkeypatch):
    monkeypatch.setattr(mod.settings, "sns_enabled", False)
    publisher = EventPublisher()
    publisher._client = MagicMock()

    await publisher.publish("document_created", {"id": uuid.uuid4()})

    publisher._client.publish.assert_not_called()


async def test_publish_sends_the_event_to_the_configured_topic(sns_enabled):
    client = MagicMock()
    publisher = EventPublisher()
    publisher._client = client
    doc_id = uuid.uuid4()

    await publisher.publish("document_updated", {"id": doc_id})

    kwargs = client.publish.call_args.kwargs
    assert kwargs["TopicArn"] == "arn:aws:sns:us-east-1:000:events"
    assert kwargs["MessageAttributes"]["event_type"]["StringValue"] == "document_updated"
    message = json.loads(kwargs["Message"])
    assert message["event_type"] == "document_updated"
    assert message["payload"] == {"id": str(doc_id)}
    assert message["timestamp"]


async def test_publish_swallows_downstream_failures(sns_enabled):
    client = MagicMock()
    client.publish.side_effect = RuntimeError("sns unavailable")
    publisher = EventPublisher()
    publisher._client = client

    await publisher.publish("document_deleted", {"id": "d-1"})

    client.publish.assert_called_once()
