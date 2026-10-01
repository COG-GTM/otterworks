"""Tests for the DOC_SVC_CREATE_ALWAYS_FAIL demo failure point."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from httpx import AsyncClient

from app.api import documents as documents_api
from app.config import Settings, settings
from app.services import alerts
from app.services.event_publisher import (
    EventPublishError,
    event_publisher,
    forced_failure_topic_arn,
)

NOT_FOUND = ClientError(
    {"Error": {"Code": "NotFound", "Message": "Topic does not exist"}}, "Publish"
)


@pytest.fixture
def sns_client(monkeypatch):
    client = MagicMock()
    client.publish.side_effect = NOT_FOUND
    monkeypatch.setattr(event_publisher, "_client", client)
    return client


@pytest.fixture
def sent_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(
        documents_api,
        "notify_document_create_failure",
        lambda title, error, reporter: sent.append((title, error, reporter)),
    )
    return sent


@pytest.mark.asyncio
async def test_create_fails_with_sns_error_and_alerts_when_switch_on(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch, sns_client, sent_alerts
):
    monkeypatch.setattr(settings, "create_always_fail", True)
    monkeypatch.setattr(
        settings, "sns_topic_arn", "arn:aws:sns:us-east-1:000000000000:otterworks-events"
    )

    for _ in range(2):
        resp = await client.post(
            "/api/v1/documents",
            json={"title": "Untitled document"},
            headers={"X-User-Email": "preston@example.com"},
        )
        assert resp.status_code == 424
        assert resp.json() == {
            "error": "event_error",
            "message": "SNS error: NotFound: Topic does not exist",
        }

    assert sns_client.publish.call_args.kwargs["TopicArn"] == (
        "arn:aws:sns:us-east-1:000000000000:otterworks-events-v2"
    )
    assert (
        sent_alerts
        == [
            (
                "Untitled document",
                "SNS error: NotFound: Topic does not exist",
                "preston@example.com",
            )
        ]
        * 2
    )

    listing = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert listing.json()["total"] == 0


@pytest.mark.asyncio
async def test_create_succeeds_without_forced_publish_when_switch_off(
    client: AsyncClient, monkeypatch, sns_client, sent_alerts
):
    monkeypatch.setattr(settings, "create_always_fail", False)

    resp = await client.post("/api/v1/documents", json={"title": "Untitled document"})

    assert resp.status_code == 201
    sns_client.publish.assert_not_called()
    assert sent_alerts == []


@pytest.mark.asyncio
async def test_publish_or_raise_reports_concise_sns_error(sns_client):
    with pytest.raises(EventPublishError, match="^SNS error: NotFound: Topic does not exist$"):
        await event_publisher.publish_or_raise("document_created", {}, "arn:missing")


def test_forced_failure_topic_defaults_to_v2_of_events_topic(monkeypatch):
    monkeypatch.setattr(settings, "sns_topic_arn", "")
    monkeypatch.setattr(settings, "aws_region", "us-west-2")
    assert forced_failure_topic_arn() == ("arn:aws:sns:us-west-2:000000000000:otterworks-events-v2")


def test_document_create_failure_payload():
    payload = alerts.build_document_create_failure_payload(
        "Q3 plan", "SNS error: NotFound: Topic does not exist", " preston@example.com "
    )

    assert payload["alert"] == "DocumentCreateFailed"
    assert payload["service"] == "document-service"
    assert payload["repository"] == "COG-GTM/otterworks"
    assert payload["summary"] == "Document creation failed: Q3 plan"
    assert payload["error"] == "SNS error: NotFound: Topic does not exist"
    assert payload["reporter_email"] == "preston@example.com"
    assert payload["occurred_at"]


def test_document_create_failure_payload_omits_blank_reporter():
    payload = alerts.build_document_create_failure_payload("Doc", "boom", "  ")
    assert "reporter_email" not in payload


@pytest.mark.asyncio
async def test_deliver_posts_to_automation_webhook_with_secret(monkeypatch):
    monkeypatch.setenv("DEVIN_AUTOMATION_WEBHOOK_URL", "https://hooks.example.test/inbox")
    monkeypatch.setenv("DEVIN_AUTOMATION_WEBHOOK_SECRET", "s3cret")
    calls = []

    async def fake_post(self, url, json, headers):
        calls.append((url, json, headers))
        return MagicMock(status_code=202)

    monkeypatch.setattr(alerts.httpx.AsyncClient, "post", fake_post)

    await alerts._deliver({"alert": "DocumentCreateFailed"})

    assert calls == [
        (
            "https://hooks.example.test/inbox",
            {"alert": "DocumentCreateFailed"},
            {"X-Webhook-Secret": "s3cret"},
        )
    ]


@pytest.mark.asyncio
async def test_deliver_skips_without_webhook_url(monkeypatch):
    monkeypatch.delenv("DEVIN_AUTOMATION_WEBHOOK_URL", raising=False)

    async def fail_post(*args, **kwargs):
        raise AssertionError("should not post")

    monkeypatch.setattr(alerts.httpx.AsyncClient, "post", fail_post)

    await alerts._deliver({"alert": "DocumentCreateFailed"})


def test_create_switch_defaults_off_and_is_not_set_by_the_image(monkeypatch):
    monkeypatch.delenv("DOC_SVC_CREATE_ALWAYS_FAIL", raising=False)
    assert Settings(_env_file=None).create_always_fail is False

    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    env_lines = [line for line in dockerfile.splitlines() if line.lstrip().startswith("ENV")]
    assert not any("DOC_SVC_CREATE_ALWAYS_FAIL" in line for line in env_lines)


@pytest.mark.asyncio
async def test_create_publishes_document_created_to_configured_topic_when_switch_off(
    client: AsyncClient, owner_id: uuid.UUID, monkeypatch, sent_alerts
):
    topic = "arn:aws:sns:us-east-1:000000000000:otterworks-events"
    sns = MagicMock()
    monkeypatch.setattr(event_publisher, "_client", sns)
    monkeypatch.setattr(settings, "create_always_fail", False)
    monkeypatch.setattr(settings, "sns_enabled", True)
    monkeypatch.setattr(settings, "sns_topic_arn", topic)

    resp = await client.post("/api/v1/documents", json={"title": "Untitled document"})

    assert resp.status_code == 201
    sns.publish.assert_called_once()
    published = sns.publish.call_args.kwargs
    assert published["TopicArn"] == topic
    assert published["MessageAttributes"]["event_type"]["StringValue"] == "document_created"
    assert sent_alerts == []

    listing = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert listing.json()["total"] == 1
