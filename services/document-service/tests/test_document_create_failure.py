"""Tests for the DOC_SVC_CREATE_ALWAYS_FAIL demo failure point."""

import uuid
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from httpx import AsyncClient

from app.api import documents as documents_api
from app.config import settings
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
        assert resp.status_code == 503
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

    alert = payload["alerts"][0]
    assert payload["status"] == "firing"
    assert alert["labels"] == {
        "alertname": "DocumentCreateFailed",
        "severity": "critical",
        "affected_service": "document-service",
        "dedup": "false",
        "reporter_email": "preston@example.com",
    }
    assert alert["annotations"]["summary"] == "Document creation failed: Q3 plan"
    assert "SNS error: NotFound" in alert["annotations"]["description"]


def test_document_create_failure_payload_omits_blank_reporter():
    payload = alerts.build_document_create_failure_payload("Doc", "boom", "  ")
    assert "reporter_email" not in payload["alerts"][0]["labels"]
