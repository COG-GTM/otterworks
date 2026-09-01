"""Tests for the SQS event consumer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.sqs_consumer import SQSConsumer

QUEUE_URL = "https://sqs.test.local/queue/search-index"


@pytest.fixture()
def consumer() -> SQSConsumer:
    """Consumer wired to a mock indexer; no AWS client is ever created."""
    return SQSConsumer(indexer=MagicMock(), queue_url=QUEUE_URL)


class TestLifecycle:
    """Tests for start/stop and client creation."""

    def test_start_without_queue_url_does_not_spawn_thread(self):
        """A consumer with no queue URL configured stays idle."""
        idle = SQSConsumer(indexer=MagicMock(), queue_url="")
        idle.start()
        assert idle._thread is None
        assert idle._running is False

    def test_start_spawns_daemon_thread_and_stop_joins_it(self, consumer):
        """start() runs the poll loop on a daemon thread that stop() ends."""
        with patch.object(SQSConsumer, "_poll_loop") as poll_loop:
            consumer.start()
            assert consumer._running is True
            assert consumer._thread is not None
            assert consumer._thread.daemon is True
            assert consumer._thread.name == "sqs-consumer"
            consumer._thread.join(timeout=5)
        poll_loop.assert_called_once_with()

        consumer.stop()
        assert consumer._running is False

    def test_stop_waits_for_a_running_poll_thread(self, consumer):
        """A live poll thread is joined with a bounded timeout."""
        thread = MagicMock()
        thread.is_alive.return_value = True
        consumer._running = True
        consumer._thread = thread

        consumer.stop()

        assert consumer._running is False
        thread.join.assert_called_once_with(timeout=5)

    def test_stop_without_start_is_a_noop(self, consumer):
        """stop() on a consumer that never started just clears the flag."""
        consumer.stop()
        assert consumer._running is False
        assert consumer._thread is None

    def test_create_sqs_client_uses_region_only_by_default(self, consumer):
        """Without an endpoint override boto3 is called with just the region."""
        boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": boto3}):
            client = consumer._create_sqs_client()
        boto3.client.assert_called_once_with("sqs", region_name="us-east-1")
        assert client is boto3.client.return_value

    def test_create_sqs_client_passes_endpoint_url_when_set(self):
        """A LocalStack-style endpoint override is forwarded to boto3."""
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
        """Every message in a batch is dispatched, using the configured poll args."""
        sqs = MagicMock()
        messages = [{"ReceiptHandle": "rh-1"}, {"ReceiptHandle": "rh-2"}]

        def receive_message(**_kwargs):
            consumer._running = False
            return {"Messages": messages}

        sqs.receive_message.side_effect = receive_message
        consumer._running = True

        with (
            patch.object(consumer, "_create_sqs_client", return_value=sqs),
            patch.object(consumer, "_process_message") as process,
        ):
            consumer._poll_loop()

        sqs.receive_message.assert_called_once_with(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
            VisibilityTimeout=60,
        )
        assert [call.args[1] for call in process.call_args_list] == messages

    def test_poll_loop_backs_off_and_retries_after_a_receive_error(self, consumer):
        """A transient receive failure sleeps instead of killing the loop."""
        sqs = MagicMock()
        sqs.receive_message.side_effect = [RuntimeError("throttled"), {"Messages": []}]
        consumer._running = True

        def stop_after_backoff(_seconds):
            consumer._running = False

        with (
            patch.object(consumer, "_create_sqs_client", return_value=sqs),
            patch("app.services.sqs_consumer.time.sleep", side_effect=stop_after_backoff) as sleep,
        ):
            consumer._poll_loop()

        sleep.assert_called_once_with(5)
        assert sqs.receive_message.call_count == 1


class TestNormalizeEvent:
    """Tests for _normalize_event across the three payload shapes."""

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
        """document-service style events map onto indexer actions."""
        result = SQSConsumer._normalize_event(
            {"event_type": event_type, "payload": {"id": "d-1"}}
        )
        assert result == {"action": expected_action, "data": {"id": "d-1"}}

    def test_unknown_snake_case_event_keeps_its_own_event_type(self):
        """An unmapped snake_case event falls through with its raw type."""
        result = SQSConsumer._normalize_event(
            {"event_type": "document_archived", "payload": {"id": "d-2"}}
        )
        assert result == {"action": "document_archived", "data": {"id": "d-2"}}

    def test_camelcase_upload_event_is_mapped_to_snake_case_fields(self):
        """file-service camelCase uploads become indexer-shaped file data."""
        result = SQSConsumer._normalize_event({
            "eventType": "file_uploaded",
            "fileId": "f-1",
            "name": "budget.xlsx",
            "mimeType": "application/vnd.ms-excel",
            "ownerId": "u-1",
            "folderId": "fold-1",
            "sizeBytes": 2048,
            "tags": ["finance"],
            "timestamp": "2026-07-31T00:00:00Z",
        })
        assert result == {
            "action": "index_file",
            "data": {
                "id": "f-1",
                "name": "budget.xlsx",
                "mime_type": "application/vnd.ms-excel",
                "owner_id": "u-1",
                "folder_id": "fold-1",
                "size": 2048,
                "tags": ["finance"],
                "created_at": "2026-07-31T00:00:00Z",
                "updated_at": "2026-07-31T00:00:00Z",
            },
        }

    def test_camelcase_event_defaults_missing_fields(self):
        """Absent camelCase metadata falls back to empty values, not KeyErrors."""
        result = SQSConsumer._normalize_event({"eventType": "file_created"})
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
    def test_camelcase_delete_event_carries_only_type_and_id(self, event_type):
        """Deletes need no metadata, just the file identity."""
        result = SQSConsumer._normalize_event({"eventType": event_type, "fileId": "f-9"})
        assert result == {"action": "delete", "data": {"type": "file", "id": "f-9"}}

    @pytest.mark.parametrize("event_type", ["file_shared", "file_moved"])
    def test_unindexable_camelcase_event_is_passed_through_untouched(self, event_type):
        """Events without file metadata are returned as-is so the indexer skips them."""
        body = {"eventType": event_type, "fileId": "f-1"}
        assert SQSConsumer._normalize_event(body) == body

    def test_indexer_shaped_event_is_returned_unchanged(self):
        """A payload already in indexer format needs no normalization."""
        body = {"action": "index_document", "data": {"id": "d-3"}}
        assert SQSConsumer._normalize_event(body) is body


class TestProcessMessage:
    """Tests for single-message handling and delete/redeliver semantics."""

    def test_successful_message_is_indexed_and_deleted(self, consumer):
        """A well-formed event reaches the indexer and the message is acked."""
        sqs = MagicMock()
        message = {
            "ReceiptHandle": "rh-1",
            "Body": json.dumps({"event_type": "document_created", "payload": {"id": "d-1"}}),
        }

        consumer._process_message(sqs, message)

        consumer.indexer.process_event.assert_called_once_with(
            {"action": "index_document", "data": {"id": "d-1"}}
        )
        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-1")

    def test_sns_envelope_is_unwrapped_before_indexing(self, consumer):
        """SNS-wrapped notifications are unwrapped to their inner event."""
        inner = {"event_type": "file_uploaded", "payload": {"id": "f-1"}}
        message = {
            "ReceiptHandle": "rh-2",
            "Body": json.dumps({"TopicArn": "arn:aws:sns:::events", "Message": json.dumps(inner)}),
        }

        consumer._process_message(MagicMock(), message)

        consumer.indexer.process_event.assert_called_once_with(
            {"action": "index_file", "data": {"id": "f-1"}}
        )

    def test_invalid_json_is_dropped_without_indexing(self, consumer):
        """Undecodable bodies are acked so they do not poison the queue."""
        sqs = MagicMock()

        consumer._process_message(sqs, {"ReceiptHandle": "rh-3", "Body": "not-json"})

        consumer.indexer.process_event.assert_not_called()
        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-3")

    def test_validation_failure_is_dropped_without_retry(self, consumer):
        """A payload the indexer rejects is acked rather than redelivered forever."""
        sqs = MagicMock()
        consumer.indexer.process_event.side_effect = ValueError("Document 'id' is required")

        consumer._process_message(
            sqs,
            {"ReceiptHandle": "rh-4", "Body": json.dumps({"action": "index_document", "data": {}})},
        )

        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-4")

    def test_unexpected_error_leaves_the_message_on_the_queue(self, consumer):
        """A downstream outage must not ack the message."""
        sqs = MagicMock()
        consumer.indexer.process_event.side_effect = RuntimeError("meilisearch down")

        consumer._process_message(
            sqs,
            {"ReceiptHandle": "rh-5", "Body": json.dumps({"action": "index_document", "data": {}})},
        )

        sqs.delete_message.assert_not_called()

    def test_message_without_body_defaults_to_an_empty_event(self, consumer):
        """A body-less message normalizes to {} and is still acked."""
        sqs = MagicMock()

        consumer._process_message(sqs, {"ReceiptHandle": "rh-6"})

        consumer.indexer.process_event.assert_called_once_with({})
        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-6")
