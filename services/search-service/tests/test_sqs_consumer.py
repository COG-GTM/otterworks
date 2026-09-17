"""Tests for the SQS event consumer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.sqs_consumer import SQSConsumer

QUEUE_URL = "https://sqs.test.local/queue"


@pytest.fixture()
def consumer() -> SQSConsumer:
    """An SQSConsumer wired to a mock indexer."""
    return SQSConsumer(indexer=MagicMock(), queue_url=QUEUE_URL)


class TestNormalizeEvent:
    """Tests for SQSConsumer._normalize_event."""

    @pytest.mark.parametrize(
        ("event_type", "expected_action"),
        [
            ("document_created", "index_document"),
            ("document_updated", "index_document"),
            ("document_deleted", "delete"),
            ("file_created", "index_file"),
            ("file_uploaded", "index_file"),
            ("file_updated", "index_file"),
            ("file_deleted", "delete"),
            ("file_trashed", "delete"),
            ("file_restored", "index_file"),
        ],
    )
    def test_snake_case_event_maps_to_indexer_action(self, event_type, expected_action):
        """Nested payload events are mapped onto the indexer action names."""
        body = {"event_type": event_type, "payload": {"id": "d-1"}}

        result = SQSConsumer._normalize_event(body)

        assert result == {"action": expected_action, "data": {"id": "d-1"}}

    def test_unknown_snake_case_event_keeps_its_own_type_as_action(self):
        """An unmapped event_type is passed through as the action."""
        body = {"event_type": "document_archived", "payload": {"id": "d-2"}}

        result = SQSConsumer._normalize_event(body)

        assert result == {"action": "document_archived", "data": {"id": "d-2"}}

    @pytest.mark.parametrize(
        ("event_type", "expected_action"),
        [
            ("file_uploaded", "index_file"),
            ("file_created", "index_file"),
            ("file_updated", "index_file"),
            ("file_restored", "index_file"),
        ],
    )
    def test_camel_case_index_event_is_converted_to_snake_case(
        self, event_type, expected_action
    ):
        """camelCase file-service events are remapped to the indexer schema."""
        body = {
            "eventType": event_type,
            "fileId": "f-1",
            "name": "report.pdf",
            "mimeType": "application/pdf",
            "ownerId": "u-1",
            "folderId": "fold-1",
            "sizeBytes": 42,
            "tags": ["finance"],
            "timestamp": "2026-01-01T00:00:00Z",
        }

        result = SQSConsumer._normalize_event(body)

        assert result == {
            "action": expected_action,
            "data": {
                "id": "f-1",
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "owner_id": "u-1",
                "folder_id": "fold-1",
                "size": 42,
                "tags": ["finance"],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        }

    def test_camel_case_index_event_defaults_missing_fields(self):
        """Absent camelCase fields fall back to empty defaults."""
        result = SQSConsumer._normalize_event({"eventType": "file_uploaded"})

        assert result["data"] == {
            "id": "",
            "name": "",
            "mime_type": "",
            "owner_id": "",
            "folder_id": "",
            "size": 0,
            "tags": [],
            "created_at": None,
            "updated_at": None,
        }

    @pytest.mark.parametrize("event_type", ["file_deleted", "file_trashed"])
    def test_camel_case_delete_event_only_carries_the_id(self, event_type):
        """Delete events are reduced to the file type and id."""
        body = {"eventType": event_type, "fileId": "f-9", "name": "gone.txt"}

        result = SQSConsumer._normalize_event(body)

        assert result == {"action": "delete", "data": {"type": "file", "id": "f-9"}}

    @pytest.mark.parametrize("event_type", ["file_shared", "file_moved"])
    def test_unindexable_camel_case_event_is_passed_through(self, event_type):
        """Events without file metadata are returned untouched."""
        body = {"eventType": event_type, "fileId": "f-1"}

        assert SQSConsumer._normalize_event(body) == body

    def test_indexer_format_event_is_passed_through(self):
        """A payload already in indexer format is returned untouched."""
        body = {"action": "index_document", "data": {"id": "d-1"}}

        assert SQSConsumer._normalize_event(body) == body


class TestLifecycle:
    """Tests for start/stop and client construction."""

    def test_start_without_queue_url_does_not_spawn_a_thread(self):
        """With no queue configured the consumer is a no-op."""
        consumer = SQSConsumer(indexer=MagicMock(), queue_url="")

        consumer.start()

        assert consumer._thread is None
        assert consumer._running is False

    def test_start_runs_the_poll_loop_in_a_daemon_thread(self, consumer):
        """start() spawns a named daemon thread targeting the poll loop."""
        with patch("app.services.sqs_consumer.threading.Thread") as thread_cls:
            consumer.start()

        thread_cls.assert_called_once()
        kwargs = thread_cls.call_args.kwargs
        assert kwargs["target"] == consumer._poll_loop
        assert kwargs["daemon"] is True
        assert kwargs["name"] == "sqs-consumer"
        thread_cls.return_value.start.assert_called_once()
        assert consumer._running is True

    def test_stop_joins_a_running_thread(self, consumer):
        """stop() clears the running flag and joins a live thread."""
        thread = MagicMock()
        thread.is_alive.return_value = True
        consumer._thread = thread
        consumer._running = True

        consumer.stop()

        assert consumer._running is False
        thread.join.assert_called_once_with(timeout=5)

    def test_stop_without_a_thread_is_a_no_op(self, consumer):
        """stop() is safe when the consumer was never started."""
        consumer.stop()

        assert consumer._running is False

    def test_create_sqs_client_uses_the_configured_region(self, consumer):
        """boto3 is called with only the region when no endpoint is set."""
        boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": boto3}):
            client = consumer._create_sqs_client()

        boto3.client.assert_called_once_with("sqs", region_name="us-east-1")
        assert client is boto3.client.return_value

    def test_create_sqs_client_passes_a_custom_endpoint(self):
        """A configured endpoint_url (e.g. LocalStack) is forwarded to boto3."""
        consumer = SQSConsumer(
            indexer=MagicMock(),
            queue_url=QUEUE_URL,
            region="eu-west-1",
            endpoint_url="http://localstack:4566",
        )
        boto3 = MagicMock()

        with patch.dict("sys.modules", {"boto3": boto3}):
            consumer._create_sqs_client()

        boto3.client.assert_called_once_with(
            "sqs", region_name="eu-west-1", endpoint_url="http://localstack:4566"
        )


class TestPollLoop:
    """Tests for the receive/dispatch loop."""

    def test_poll_loop_processes_each_received_message_then_exits(self, consumer):
        """Every message in a batch is dispatched to _process_message."""
        sqs = MagicMock()
        sqs.receive_message.return_value = {
            "Messages": [{"MessageId": "1"}, {"MessageId": "2"}]
        }
        consumer._running = True

        def stop_after_first_batch(_sqs, _message):
            consumer._running = False

        with (
            patch.object(consumer, "_create_sqs_client", return_value=sqs),
            patch.object(
                consumer, "_process_message", side_effect=stop_after_first_batch
            ) as process,
        ):
            consumer._poll_loop()

        sqs.receive_message.assert_called_once_with(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
            VisibilityTimeout=60,
        )
        assert process.call_count == 2

    def test_poll_loop_backs_off_and_retries_after_a_receive_error(self, consumer):
        """A receive failure sleeps rather than killing the loop."""
        sqs = MagicMock()
        sqs.receive_message.side_effect = RuntimeError("sqs down")
        consumer._running = True

        def stop_running(_seconds):
            consumer._running = False

        with (
            patch.object(consumer, "_create_sqs_client", return_value=sqs),
            patch("app.services.sqs_consumer.time.sleep", side_effect=stop_running) as sleep,
        ):
            consumer._poll_loop()

        sleep.assert_called_once_with(5)

    def test_poll_loop_exits_immediately_when_not_running(self, consumer):
        """A stopped consumer never calls receive_message."""
        sqs = MagicMock()

        with patch.object(consumer, "_create_sqs_client", return_value=sqs):
            consumer._poll_loop()

        sqs.receive_message.assert_not_called()


class TestProcessMessage:
    """Tests for single-message handling."""

    def test_plain_message_is_indexed_and_deleted(self, consumer):
        """A well-formed message is handed to the indexer then acked."""
        sqs = MagicMock()
        message = {
            "ReceiptHandle": "rh-1",
            "Body": json.dumps({"action": "index_document", "data": {"id": "d-1"}}),
        }

        consumer._process_message(sqs, message)

        consumer.indexer.process_event.assert_called_once_with(
            {"action": "index_document", "data": {"id": "d-1"}}
        )
        sqs.delete_message.assert_called_once_with(
            QueueUrl=QUEUE_URL, ReceiptHandle="rh-1"
        )

    def test_sns_wrapped_message_is_unwrapped_before_normalizing(self, consumer):
        """SNS envelopes are unwrapped and the inner event normalized."""
        sqs = MagicMock()
        inner = {"event_type": "document_created", "payload": {"id": "d-1"}}
        message = {
            "ReceiptHandle": "rh-2",
            "Body": json.dumps(
                {"TopicArn": "arn:aws:sns:::topic", "Message": json.dumps(inner)}
            ),
        }

        consumer._process_message(sqs, message)

        consumer.indexer.process_event.assert_called_once_with(
            {"action": "index_document", "data": {"id": "d-1"}}
        )
        sqs.delete_message.assert_called_once_with(
            QueueUrl=QUEUE_URL, ReceiptHandle="rh-2"
        )

    def test_invalid_json_is_dropped(self, consumer):
        """An unparseable body is acked so it is not redelivered forever."""
        sqs = MagicMock()

        consumer._process_message(sqs, {"ReceiptHandle": "rh-3", "Body": "not-json"})

        consumer.indexer.process_event.assert_not_called()
        sqs.delete_message.assert_called_once_with(
            QueueUrl=QUEUE_URL, ReceiptHandle="rh-3"
        )

    def test_validation_error_drops_the_message(self, consumer):
        """A ValueError from the indexer means the payload is unusable."""
        sqs = MagicMock()
        consumer.indexer.process_event.side_effect = ValueError("id is required")

        consumer._process_message(
            sqs,
            {"ReceiptHandle": "rh-4", "Body": json.dumps({"action": "index_file"})},
        )

        sqs.delete_message.assert_called_once_with(
            QueueUrl=QUEUE_URL, ReceiptHandle="rh-4"
        )

    def test_unexpected_error_keeps_the_message_for_redelivery(self, consumer):
        """A transient downstream failure must not ack the message."""
        sqs = MagicMock()
        consumer.indexer.process_event.side_effect = RuntimeError("meilisearch down")

        consumer._process_message(
            sqs,
            {"ReceiptHandle": "rh-5", "Body": json.dumps({"action": "index_file"})},
        )

        sqs.delete_message.assert_not_called()
