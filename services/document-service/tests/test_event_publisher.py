"""Tests for the SNS event publisher."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

import app.services.event_publisher as publisher_mod
from app.services.event_publisher import EventPublisher, _UUIDEncoder


def test_uuid_encoder_serialises_uuid_and_datetime():
    doc_id = uuid.uuid4()
    created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    encoded = json.loads(json.dumps({"id": doc_id, "at": created}, cls=_UUIDEncoder))

    assert encoded == {"id": str(doc_id), "at": created.isoformat()}


def test_uuid_encoder_rejects_unsupported_types():
    with pytest.raises(TypeError):
        json.dumps({"obj": object()}, cls=_UUIDEncoder)


def test_get_client_is_cached_and_uses_configured_region(monkeypatch):
    monkeypatch.setattr(publisher_mod.settings, "aws_region", "eu-west-1")
    monkeypatch.setattr(publisher_mod.settings, "aws_endpoint_url", "")
    calls = []
    fake_client = MagicMock()

    class _FakeBoto3:
        @staticmethod
        def client(service, **kwargs):
            calls.append((service, kwargs))
            return fake_client

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3)

    publisher = EventPublisher()
    assert publisher._get_client() is fake_client
    assert publisher._get_client() is fake_client
    assert calls == [("sns", {"region_name": "eu-west-1"})]


def test_get_client_passes_endpoint_url_when_configured(monkeypatch):
    monkeypatch.setattr(publisher_mod.settings, "aws_region", "us-east-1")
    monkeypatch.setattr(publisher_mod.settings, "aws_endpoint_url", "http://localstack:4566")
    calls = []

    class _FakeBoto3:
        @staticmethod
        def client(service, **kwargs):
            calls.append(kwargs)
            return MagicMock()

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3)

    EventPublisher()._get_client()

    assert calls[0]["endpoint_url"] == "http://localstack:4566"


@pytest.mark.asyncio
async def test_publish_skips_when_sns_disabled(monkeypatch):
    monkeypatch.setattr(publisher_mod.settings, "sns_enabled", False)
    publisher = EventPublisher()
    publisher._client = MagicMock()

    await publisher.publish("document_created", {"id": "d-1"})

    publisher._client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_publish_sends_message_to_sns(monkeypatch):
    monkeypatch.setattr(publisher_mod.settings, "sns_enabled", True)
    monkeypatch.setattr(publisher_mod.settings, "sns_topic_arn", "arn:aws:sns:::events")
    publisher = EventPublisher()
    client = MagicMock()
    publisher._client = client
    doc_id = uuid.uuid4()

    await publisher.publish("document_created", {"id": doc_id})

    kwargs = client.publish.call_args.kwargs
    assert kwargs["TopicArn"] == "arn:aws:sns:::events"
    assert kwargs["MessageAttributes"] == {
        "event_type": {"DataType": "String", "StringValue": "document_created"}
    }
    message = json.loads(kwargs["Message"])
    assert message["event_type"] == "document_created"
    assert message["payload"] == {"id": str(doc_id)}
    assert datetime.fromisoformat(message["timestamp"]).tzinfo is not None


@pytest.mark.asyncio
async def test_publish_swallows_sns_errors(monkeypatch):
    monkeypatch.setattr(publisher_mod.settings, "sns_enabled", True)
    monkeypatch.setattr(publisher_mod.settings, "sns_topic_arn", "arn:aws:sns:::events")
    publisher = EventPublisher()
    client = MagicMock()
    client.publish.side_effect = RuntimeError("sns unavailable")
    publisher._client = client

    await publisher.publish("document_deleted", {"id": "d-1"})

    client.publish.assert_called_once()
