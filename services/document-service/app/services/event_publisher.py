"""SNS event publishing for domain events."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings

logger = structlog.get_logger()


class _UUIDEncoder(json.JSONEncoder):
    def default(self, o: object) -> Any:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


class EventPublishError(Exception):
    """An SNS publish failed; ``str()`` is a concise ``SNS error: <code>: <message>``."""


def forced_failure_topic_arn() -> str:
    """The real topic ARN with a ``-v2`` suffix: a plausible topic that does not exist."""
    base = settings.sns_topic_arn or (
        f"arn:aws:sns:{settings.aws_region}:000000000000:otterworks-events"
    )
    return f"{base}-v2"


def _encode(event_type: str, payload: dict[str, Any]) -> str:
    message = {
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
    return json.dumps(message, cls=_UUIDEncoder)


class EventPublisher:
    """Publishes domain events to AWS SNS."""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):  # noqa: ANN202
        if self._client is None:
            import boto3

            kwargs = {"region_name": settings.aws_region}
            if settings.aws_endpoint_url:
                kwargs["endpoint_url"] = settings.aws_endpoint_url
            self._client = boto3.client("sns", **kwargs)
        return self._client

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if not settings.sns_enabled:
            logger.info("sns_event_skipped", event_type=event_type)
            return

        try:
            client = self._get_client()
            await asyncio.to_thread(
                client.publish,
                TopicArn=settings.sns_topic_arn,
                Message=_encode(event_type, payload),
                MessageAttributes={
                    "event_type": {"DataType": "String", "StringValue": event_type}
                },
            )
            logger.info("sns_event_published", event_type=event_type)
        except Exception:
            logger.exception("sns_publish_failed", event_type=event_type)

    async def publish_or_raise(
        self, event_type: str, payload: dict[str, Any], topic_arn: str
    ) -> None:
        """Publish to ``topic_arn`` regardless of ``sns_enabled``; raise on failure."""
        try:
            client = self._get_client()
            await asyncio.to_thread(
                client.publish,
                TopicArn=topic_arn,
                Message=_encode(event_type, payload),
                MessageAttributes={
                    "event_type": {"DataType": "String", "StringValue": event_type}
                },
            )
        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = error.get("Code", "Unknown")
            detail = error.get("Message", "")
            raise EventPublishError(f"SNS error: {code}: {detail}") from exc
        except BotoCoreError as exc:
            raise EventPublishError(f"SNS error: {exc}") from exc
        logger.info("sns_event_published", event_type=event_type, topic_arn=topic_arn)


event_publisher = EventPublisher()
