"""Tests for the SNS event publisher."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import boto3
import pytest

import app.services.event_publisher as mod
from app.services.event_publisher import EventPublisher, _UUIDEncoder


def test_uuid_encoder_serialises_uuid_and_datetime():
    uid = UUID("11111111-2222-3333-4444-555555555555")
    moment = datetime(2026, 7, 30, 12, 30, tzinfo=UTC)

    encoded = json.loads(json.dumps({"id": uid, "at": moment}, cls=_UUIDEncoder))

    assert encoded == {"id": str(uid), "at": moment.isoformat()}


def test_uuid_encoder_rejects_unsupported_types():
    with pytest.raises(TypeError):
        json.dumps({"thing": object()}, cls=_UUIDEncoder)


def test_get_client_builds_sns_client_once(monkeypatch):
    created: list[tuple[str, dict]] = []

    def _fake_client(service_name, **kwargs):
        created.append((service_name, kwargs))
        return MagicMock(name="sns")

    monkeypatch.setattr(boto3, "client", _fake_client)
    monkeypatch.setattr(mod.settings, "aws_region", "eu-west-1")
    monkeypatch.setattr(mod.settings, "aws_endpoint_url", "")

    publisher = EventPublisher()
    first = publisher._get_client()
    second = publisher._get_client()

    assert first is second
    assert created == [("sns", {"region_name": "eu-west-1"})]


def test_get_client_honours_custom_endpoint_url(monkeypatch):
    created: list[dict] = []

    def _fake_client(_service_name, **kwargs):
        created.append(kwargs)
        return MagicMock(name="sns")

    monkeypatch.setattr(boto3, "client", _fake_client)
    monkeypatch.setattr(mod.settings, "aws_region", "us-east-1")
    monkeypatch.setattr(mod.settings, "aws_endpoint_url", "http://localstack:4566")

    EventPublisher()._get_client()

    assert created == [
        {"region_name": "us-east-1", "endpoint_url": "http://localstack:4566"}
    ]


@pytest.mark.asyncio
async def test_publish_skips_when_sns_disabled(monkeypatch):
    monkeypatch.setattr(mod.settings, "sns_enabled", False)
    publisher = EventPublisher()
    publisher._client = MagicMock()

    await publisher.publish("document_created", {"id": "d-1"})

    publisher._client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_publish_sends_serialised_event_to_sns(monkeypatch):
    monkeypatch.setattr(mod.settings, "sns_enabled", True)
    monkeypatch.setattr(mod.settings, "sns_topic_arn", "arn:aws:sns:::documents")
    document_id = UUID("11111111-2222-3333-4444-555555555555")
    client = MagicMock()
    publisher = EventPublisher()
    publisher._client = client

    await publisher.publish("document_created", {"id": document_id})

    kwargs = client.publish.call_args.kwargs
    assert kwargs["TopicArn"] == "arn:aws:sns:::documents"
    assert kwargs["MessageAttributes"] == {
        "event_type": {"DataType": "String", "StringValue": "document_created"}
    }
    message = json.loads(kwargs["Message"])
    assert message["event_type"] == "document_created"
    assert message["payload"] == {"id": str(document_id)}
    assert datetime.fromisoformat(message["timestamp"]).tzinfo is not None


@pytest.mark.asyncio
async def test_publish_swallows_downstream_failures(monkeypatch):
    monkeypatch.setattr(mod.settings, "sns_enabled", True)
    monkeypatch.setattr(mod.settings, "sns_topic_arn", "arn:aws:sns:::documents")
    client = MagicMock()
    client.publish.side_effect = RuntimeError("sns unreachable")
    publisher = EventPublisher()
    publisher._client = client

    await publisher.publish("document_deleted", {"id": "d-1"})

    client.publish.assert_called_once()
