"""Tests for the SQS consumer.

The consumer is exercised without ever starting a real background thread or
touching AWS: boto3, the SQS client and the indexer are all mocked at the
boundary.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.sqs_consumer import SQSConsumer


@pytest.fixture()
def indexer() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def consumer(indexer: MagicMock) -> SQSConsumer:
    return SQSConsumer(indexer=indexer, queue_url="https://sqs.test/q")


class TestLifecycle:
    """start()/stop() and lazy client creation."""

    def test_defaults_are_applied(self, indexer: MagicMock):
        consumer = SQSConsumer(indexer=indexer, queue_url="https://sqs.test/q")
        assert consumer.region == "us-east-1"
        assert consumer.endpoint_url == ""
        assert consumer.max_messages == 10
        assert consumer.wait_time_seconds == 20
        assert consumer.visibility_timeout == 60
        assert consumer._running is False
        assert consumer._thread is None

    def test_start_without_queue_url_does_not_spawn_thread(self, indexer: MagicMock):
        consumer = SQSConsumer(indexer=indexer, queue_url="")
        with patch("app.services.sqs_consumer.threading.Thread") as thread_cls:
            consumer.start()
        thread_cls.assert_not_called()
        assert consumer._thread is None
        assert consumer._running is False

    def test_start_spawns_a_daemon_thread_running_the_poll_loop(self, consumer: SQSConsumer):
        with patch("app.services.sqs_consumer.threading.Thread") as thread_cls:
            consumer.start()

        thread_cls.assert_called_once_with(
            target=consumer._poll_loop, daemon=True, name="sqs-consumer"
        )
        thread_cls.return_value.start.assert_called_once_with()
        assert consumer._running is True
        assert consumer._thread is thread_cls.return_value

    def test_stop_joins_a_live_thread(self, consumer: SQSConsumer):
        thread = MagicMock()
        thread.is_alive.return_value = True
        consumer._thread = thread
        consumer._running = True

        consumer.stop()

        assert consumer._running is False
        thread.join.assert_called_once_with(timeout=5)

    def test_stop_without_a_thread_is_a_noop(self, consumer: SQSConsumer):
        consumer.stop()
        assert consumer._running is False

    def test_create_sqs_client_uses_region_only_by_default(self, consumer: SQSConsumer):
        with patch("boto3.client") as boto_client:
            client = consumer._create_sqs_client()

        boto_client.assert_called_once_with("sqs", region_name="us-east-1")
        assert client is boto_client.return_value

    def test_create_sqs_client_passes_endpoint_url_when_set(self, indexer: MagicMock):
        consumer = SQSConsumer(
            indexer=indexer,
            queue_url="https://sqs.test/q",
            region="eu-west-1",
            endpoint_url="http://localstack:4566",
        )
        with patch("boto3.client") as boto_client:
            consumer._create_sqs_client()

        boto_client.assert_called_once_with(
            "sqs", region_name="eu-west-1", endpoint_url="http://localstack:4566"
        )


class TestPollLoop:
    """_poll_loop dispatches received messages and survives SQS errors."""

    def test_poll_loop_processes_each_received_message(self, consumer: SQSConsumer):
        sqs = MagicMock()
        messages = [{"ReceiptHandle": "rh-1"}, {"ReceiptHandle": "rh-2"}]

        def receive(**_kwargs):
            consumer._running = False
            return {"Messages": messages}

        sqs.receive_message.side_effect = receive
        consumer._create_sqs_client = MagicMock(return_value=sqs)
        consumer._process_message = MagicMock()
        consumer._running = True

        consumer._poll_loop()

        sqs.receive_message.assert_called_once_with(
            QueueUrl="https://sqs.test/q",
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
            VisibilityTimeout=60,
        )
        assert [call.args[1] for call in consumer._process_message.call_args_list] == messages

    def test_poll_loop_handles_empty_receive(self, consumer: SQSConsumer):
        sqs = MagicMock()

        def receive(**_kwargs):
            consumer._running = False
            return {}

        sqs.receive_message.side_effect = receive
        consumer._create_sqs_client = MagicMock(return_value=sqs)
        consumer._process_message = MagicMock()
        consumer._running = True

        consumer._poll_loop()

        consumer._process_message.assert_not_called()

    def test_poll_loop_backs_off_and_continues_after_an_sqs_error(self, consumer: SQSConsumer):
        sqs = MagicMock()
        sqs.receive_message.side_effect = [RuntimeError("sqs down"), {"Messages": []}]
        consumer._create_sqs_client = MagicMock(return_value=sqs)
        consumer._running = True

        with patch("app.services.sqs_consumer.time.sleep") as sleep:
            def stop_after_backoff(_seconds):
                consumer._running = False

            sleep.side_effect = stop_after_backoff
            consumer._poll_loop()

        sleep.assert_called_once_with(5)
        assert sqs.receive_message.call_count == 1


class TestNormalizeEvent:
    """_normalize_event maps the three payload shapes onto the indexer format."""

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
    def test_snake_case_event_maps_action_and_keeps_payload(self, event_type, expected_action):
        payload = {"id": "d-1", "title": "Plan"}

        result = SQSConsumer._normalize_event({"event_type": event_type, "payload": payload})

        assert result == {"action": expected_action, "data": payload}

    def test_snake_case_unknown_event_type_passes_the_type_through_as_action(self):
        result = SQSConsumer._normalize_event(
            {"event_type": "document_archived", "payload": {"id": "d-1"}}
        )
        assert result == {"action": "document_archived", "data": {"id": "d-1"}}

    @pytest.mark.parametrize(
        "event_type", ["file_uploaded", "file_created", "file_updated", "file_restored"]
    )
    def test_camelcase_index_event_is_mapped_to_snake_case_fields(self, event_type):
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

    def test_camelcase_index_event_defaults_missing_fields(self):
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
    def test_camelcase_delete_event_carries_only_the_id(self, event_type):
        result = SQSConsumer._normalize_event({"eventType": event_type, "fileId": "f-9"})

        assert result == {"action": "delete", "data": {"type": "file", "id": "f-9"}}

    @pytest.mark.parametrize("event_type", ["file_shared", "file_moved"])
    def test_camelcase_event_without_metadata_is_passed_through_untouched(self, event_type):
        body = {"eventType": event_type, "fileId": "f-1"}
        assert SQSConsumer._normalize_event(body) == body

    def test_indexer_format_event_is_returned_unchanged(self):
        body = {"action": "index_document", "data": {"id": "d-1"}}
        assert SQSConsumer._normalize_event(body) == body


class TestProcessMessage:
    """_process_message unwraps, normalizes, dispatches and acks."""

    def test_plain_message_is_processed_and_deleted(self, consumer: SQSConsumer):
        sqs = MagicMock()
        body = {"action": "index_document", "data": {"id": "d-1"}}

        consumer._process_message(sqs, {"ReceiptHandle": "rh-1", "Body": json.dumps(body)})

        consumer.indexer.process_event.assert_called_once_with(body)
        sqs.delete_message.assert_called_once_with(
            QueueUrl="https://sqs.test/q", ReceiptHandle="rh-1"
        )

    def test_sns_wrapped_message_is_unwrapped_before_dispatch(self, consumer: SQSConsumer):
        sqs = MagicMock()
        inner = {"event_type": "document_created", "payload": {"id": "d-1"}}
        message = {
            "ReceiptHandle": "rh-1",
            "Body": json.dumps({"TopicArn": "arn:aws:sns:::t", "Message": json.dumps(inner)}),
        }

        consumer._process_message(sqs, message)

        consumer.indexer.process_event.assert_called_once_with(
            {"action": "index_document", "data": {"id": "d-1"}}
        )
        sqs.delete_message.assert_called_once_with(
            QueueUrl="https://sqs.test/q", ReceiptHandle="rh-1"
        )

    def test_invalid_json_is_dropped(self, consumer: SQSConsumer):
        sqs = MagicMock()

        consumer._process_message(sqs, {"ReceiptHandle": "rh-2", "Body": "not-json"})

        consumer.indexer.process_event.assert_not_called()
        sqs.delete_message.assert_called_once_with(
            QueueUrl="https://sqs.test/q", ReceiptHandle="rh-2"
        )

    def test_missing_body_is_treated_as_an_empty_event(self, consumer: SQSConsumer):
        sqs = MagicMock()

        consumer._process_message(sqs, {"ReceiptHandle": "rh-3"})

        consumer.indexer.process_event.assert_called_once_with({})
        sqs.delete_message.assert_called_once_with(
            QueueUrl="https://sqs.test/q", ReceiptHandle="rh-3"
        )

    def test_validation_error_drops_the_message(self, consumer: SQSConsumer):
        sqs = MagicMock()
        consumer.indexer.process_event.side_effect = ValueError("Document 'id' is required")

        consumer._process_message(
            sqs, {"ReceiptHandle": "rh-4", "Body": json.dumps({"action": "index_document"})}
        )

        sqs.delete_message.assert_called_once_with(
            QueueUrl="https://sqs.test/q", ReceiptHandle="rh-4"
        )

    def test_unexpected_error_keeps_the_message_for_redelivery(self, consumer: SQSConsumer):
        sqs = MagicMock()
        consumer.indexer.process_event.side_effect = RuntimeError("meilisearch down")

        consumer._process_message(
            sqs, {"ReceiptHandle": "rh-5", "Body": json.dumps({"action": "noop", "data": {}})}
        )

        sqs.delete_message.assert_not_called()
