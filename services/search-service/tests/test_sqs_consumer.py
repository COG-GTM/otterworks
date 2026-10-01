"""Tests for the SQS consumer that feeds the search indexer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.sqs_consumer import SQSConsumer


@pytest.fixture()
def consumer() -> SQSConsumer:
    """An SQS consumer wired to a mock indexer and a fake queue URL."""
    return SQSConsumer(indexer=MagicMock(), queue_url="https://sqs.test/q")


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
    def test_snake_case_events_map_to_indexer_actions(self, event_type, expected_action):
        """snake_case events with a payload are mapped onto indexer actions."""
        result = SQSConsumer._normalize_event(
            {"event_type": event_type, "payload": {"id": "x-1"}}
        )
        assert result == {"action": expected_action, "data": {"id": "x-1"}}

    def test_unknown_snake_case_event_type_is_passed_through_as_action(self):
        """An unmapped snake_case event keeps its own event_type as the action."""
        result = SQSConsumer._normalize_event(
            {"event_type": "document_archived", "payload": {"id": "d-9"}}
        )
        assert result == {"action": "document_archived", "data": {"id": "d-9"}}

    @pytest.mark.parametrize(
        "event_type", ["file_uploaded", "file_created", "file_updated", "file_restored"]
    )
    def test_camel_case_upsert_events_are_mapped_to_snake_case_fields(self, event_type):
        """camelCase file-service events are translated into indexer file data."""
        result = SQSConsumer._normalize_event(
            {
                "eventType": event_type,
                "fileId": "f-1",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "ownerId": "u-1",
                "folderId": "fold-1",
                "sizeBytes": 2048,
                "tags": ["finance"],
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        assert result == {
            "action": "index_file",
            "data": {
                "id": "f-1",
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "owner_id": "u-1",
                "folder_id": "fold-1",
                "size": 2048,
                "tags": ["finance"],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        }

    def test_camel_case_upsert_event_defaults_missing_fields(self):
        """Missing camelCase fields fall back to empty values, not KeyError."""
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
    def test_camel_case_delete_events_carry_only_type_and_id(self, event_type):
        """Delete events are reduced to the identifiers the indexer needs."""
        result = SQSConsumer._normalize_event({"eventType": event_type, "fileId": "f-2"})
        assert result == {"action": "delete", "data": {"type": "file", "id": "f-2"}}

    @pytest.mark.parametrize("event_type", ["file_shared", "file_moved"])
    def test_unindexable_camel_case_events_are_passed_through_untouched(self, event_type):
        """Events without file metadata are returned verbatim so they are skipped."""
        body = {"eventType": event_type, "fileId": "f-3"}
        assert SQSConsumer._normalize_event(body) == body

    def test_indexer_format_event_is_returned_unchanged(self):
        """An event already in indexer format needs no normalization."""
        body = {"action": "index_document", "data": {"id": "d-1"}}
        assert SQSConsumer._normalize_event(body) == body


class TestProcessMessage:
    """Tests for SQSConsumer._process_message."""

    def test_successful_processing_deletes_the_message(self, consumer):
        """A processed message is acknowledged by deleting it from the queue."""
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
            QueueUrl="https://sqs.test/q", ReceiptHandle="rh-1"
        )

    def test_sns_wrapped_message_is_unwrapped_before_normalization(self, consumer):
        """SNS envelopes are unwrapped and the inner event normalized."""
        sqs = MagicMock()
        inner = {"event_type": "document_created", "payload": {"id": "d-2"}}
        message = {
            "ReceiptHandle": "rh-2",
            "Body": json.dumps({"TopicArn": "arn:aws:sns:::t", "Message": json.dumps(inner)}),
        }

        consumer._process_message(sqs, message)

        consumer.indexer.process_event.assert_called_once_with(
            {"action": "index_document", "data": {"id": "d-2"}}
        )
        sqs.delete_message.assert_called_once()

    def test_invalid_json_is_dropped_without_indexing(self, consumer):
        """A malformed body is deleted rather than redelivered forever."""
        sqs = MagicMock()

        consumer._process_message(sqs, {"ReceiptHandle": "rh-3", "Body": "not-json"})

        consumer.indexer.process_event.assert_not_called()
        sqs.delete_message.assert_called_once_with(
            QueueUrl="https://sqs.test/q", ReceiptHandle="rh-3"
        )

    def test_validation_error_is_dropped(self, consumer):
        """A ValueError from the indexer means the payload is unusable: drop it."""
        sqs = MagicMock()
        consumer.indexer.process_event.side_effect = ValueError("id required")

        consumer._process_message(
            sqs, {"ReceiptHandle": "rh-4", "Body": json.dumps({"action": "index_file"})}
        )

        sqs.delete_message.assert_called_once_with(
            QueueUrl="https://sqs.test/q", ReceiptHandle="rh-4"
        )

    def test_unexpected_error_keeps_the_message_for_redelivery(self, consumer):
        """A transient downstream failure must not acknowledge the message."""
        sqs = MagicMock()
        consumer.indexer.process_event.side_effect = RuntimeError("meili down")

        consumer._process_message(
            sqs, {"ReceiptHandle": "rh-5", "Body": json.dumps({"action": "noop", "data": {}})}
        )

        sqs.delete_message.assert_not_called()

    def test_missing_body_defaults_to_empty_event(self, consumer):
        """A message with no Body is normalized to an empty event and acked."""
        sqs = MagicMock()

        consumer._process_message(sqs, {"ReceiptHandle": "rh-6"})

        consumer.indexer.process_event.assert_called_once_with({})
        sqs.delete_message.assert_called_once()


class TestLifecycle:
    """Tests for start/stop and client creation."""

    def test_start_without_queue_url_does_not_spawn_a_thread(self):
        """With no queue configured the consumer stays idle."""
        consumer = SQSConsumer(indexer=MagicMock(), queue_url="")

        consumer.start()

        assert consumer._thread is None
        assert consumer._running is False

    def test_start_spawns_a_daemon_thread_running_the_poll_loop(self, consumer):
        """Starting marks the consumer running and launches the poll loop thread."""
        with patch("app.services.sqs_consumer.threading.Thread") as thread_cls:
            consumer.start()

        assert consumer._running is True
        assert thread_cls.call_args.kwargs["target"] == consumer._poll_loop
        assert thread_cls.call_args.kwargs["daemon"] is True
        thread_cls.return_value.start.assert_called_once()

    def test_stop_joins_a_live_thread(self, consumer):
        """Stopping clears the running flag and waits for the thread."""
        thread = MagicMock()
        thread.is_alive.return_value = True
        consumer._thread = thread
        consumer._running = True

        consumer.stop()

        assert consumer._running is False
        thread.join.assert_called_once_with(timeout=5)

    def test_stop_without_a_thread_is_a_noop(self, consumer):
        """Stopping a consumer that never started does not fail."""
        consumer.stop()
        assert consumer._running is False

    def test_create_sqs_client_uses_region_only_by_default(self, consumer):
        """Without an endpoint override only the region is passed to boto3."""
        boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": boto3}):
            client = consumer._create_sqs_client()

        boto3.client.assert_called_once_with("sqs", region_name="us-east-1")
        assert client is boto3.client.return_value

    def test_create_sqs_client_honours_endpoint_override(self):
        """A configured endpoint URL (e.g. LocalStack) is forwarded to boto3."""
        consumer = SQSConsumer(
            indexer=MagicMock(),
            queue_url="https://sqs.test/q",
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
    """Tests for the polling loop, driven synchronously with a mock SQS client."""

    def test_poll_loop_processes_each_received_message_then_exits(self, consumer):
        """Every message in a receive batch is handed to _process_message."""
        sqs = MagicMock()
        messages = [{"ReceiptHandle": "a"}, {"ReceiptHandle": "b"}]

        def receive(**kwargs):
            consumer._running = False  # single iteration
            assert kwargs == {
                "QueueUrl": "https://sqs.test/q",
                "MaxNumberOfMessages": 10,
                "WaitTimeSeconds": 20,
                "VisibilityTimeout": 60,
            }
            return {"Messages": messages}

        sqs.receive_message.side_effect = receive
        consumer._running = True

        with patch.object(consumer, "_create_sqs_client", return_value=sqs), patch.object(
            consumer, "_process_message"
        ) as process:
            consumer._poll_loop()

        assert [call.args[1] for call in process.call_args_list] == messages

    def test_poll_loop_handles_empty_receive_batches(self, consumer):
        """An empty long-poll response simply loops again."""
        sqs = MagicMock()

        def receive(**_kwargs):
            consumer._running = False
            return {}

        sqs.receive_message.side_effect = receive
        consumer._running = True

        with patch.object(consumer, "_create_sqs_client", return_value=sqs), patch.object(
            consumer, "_process_message"
        ) as process:
            consumer._poll_loop()

        process.assert_not_called()

    def test_poll_loop_backs_off_after_a_receive_failure(self, consumer):
        """A receive error is logged and followed by a back-off sleep."""
        sqs = MagicMock()

        def receive(**_kwargs):
            consumer._running = False
            raise RuntimeError("network down")

        sqs.receive_message.side_effect = receive
        consumer._running = True

        with patch.object(consumer, "_create_sqs_client", return_value=sqs), patch(
            "app.services.sqs_consumer.time.sleep"
        ) as sleep:
            consumer._poll_loop()

        sleep.assert_called_once_with(5)
