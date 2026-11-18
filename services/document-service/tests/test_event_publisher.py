"""SNS event publisher."""

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.services import event_publisher as ep


class _FakeSNS:
    def __init__(self, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    def publish(self, **kwargs):
        if self.fail:
            raise RuntimeError("sns down")
        self.calls.append(kwargs)


def test_encoder_serialises_uuid_and_datetime():
    uid = uuid.uuid4()
    ts = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    out = json.loads(json.dumps({"id": uid, "at": ts}, cls=ep._UUIDEncoder))
    assert out == {"id": str(uid), "at": ts.isoformat()}


def test_encoder_rejects_unknown_types():
    with pytest.raises(TypeError):
        json.dumps({"x": object()}, cls=ep._UUIDEncoder)


@pytest.mark.asyncio
async def test_publish_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(ep.settings, "sns_enabled", False)
    publisher = ep.EventPublisher()
    fake = _FakeSNS()
    publisher._client = fake
    await publisher.publish("document_created", {"id": uuid.uuid4()})
    assert fake.calls == []


@pytest.mark.asyncio
async def test_publish_sends_message(monkeypatch):
    monkeypatch.setattr(ep.settings, "sns_enabled", True)
    monkeypatch.setattr(ep.settings, "sns_topic_arn", "arn:aws:sns:us-east-1:0:docs")
    publisher = ep.EventPublisher()
    fake = _FakeSNS()
    publisher._client = fake
    doc_id = uuid.uuid4()

    await publisher.publish("document_created", {"id": doc_id})

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["TopicArn"] == "arn:aws:sns:us-east-1:0:docs"
    assert call["MessageAttributes"] == {
        "event_type": {"DataType": "String", "StringValue": "document_created"}
    }
    body = json.loads(call["Message"])
    assert body["event_type"] == "document_created"
    assert body["payload"] == {"id": str(doc_id)}
    assert datetime.fromisoformat(body["timestamp"]).tzinfo is not None


@pytest.mark.asyncio
async def test_publish_swallows_client_errors(monkeypatch):
    monkeypatch.setattr(ep.settings, "sns_enabled", True)
    publisher = ep.EventPublisher()
    publisher._client = _FakeSNS(fail=True)
    await publisher.publish("document_deleted", {"id": uuid.uuid4()})


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("", {"region_name": "eu-west-1"}),
        (
            "http://localstack:4566",
            {"region_name": "eu-west-1", "endpoint_url": "http://localstack:4566"},
        ),
    ],
)
def test_get_client_builds_boto3_client_once(monkeypatch, endpoint, expected):
    import boto3

    monkeypatch.setattr(ep.settings, "aws_region", "eu-west-1")
    monkeypatch.setattr(ep.settings, "aws_endpoint_url", endpoint)
    created = []

    def _client(service, **kwargs):
        created.append((service, kwargs))
        return object()

    monkeypatch.setattr(boto3, "client", _client)
    publisher = ep.EventPublisher()
    first = publisher._get_client()
    assert publisher._get_client() is first
    assert created == [("sns", expected)]
