"""Tests for the SQS consumer."""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.services.sqs_consumer import SQSConsumer

QUEUE_URL = "http://localhost:4566/000000000000/search-indexing"


@pytest.fixture()
def indexer() -> MagicMock:
    mock = MagicMock()
    mock.process_event.return_value = {"status": "indexed"}
    return mock


@pytest.fixture()
def consumer(indexer) -> SQSConsumer:
    return SQSConsumer(indexer=indexer, queue_url=QUEUE_URL, wait_time_seconds=0)


def _message(body, receipt: str = "rh-1") -> dict:
    raw = body if isinstance(body, str) else json.dumps(body)
    return {"MessageId": "m-1", "ReceiptHandle": receipt, "Body": raw}


class TestLifecycle:
    def test_start_without_queue_url_is_noop(self, indexer):
        consumer = SQSConsumer(indexer=indexer, queue_url="")
        consumer.start()
        assert consumer._thread is None
        assert consumer._running is False

    def test_start_and_stop(self, consumer):
        started = threading.Event()

        def fake_loop():
            started.set()
            while consumer._running:
                started.wait(0.01)

        with patch.object(consumer, "_poll_loop", side_effect=fake_loop):
            consumer.start()
            assert started.wait(2)
            assert consumer._thread.daemon
            assert consumer._thread.name == "sqs-consumer"
            consumer.stop()
        assert consumer._running is False
        assert not consumer._thread.is_alive()

    def test_stop_without_start(self, consumer):
        consumer.stop()
        assert consumer._running is False


class TestCreateClient:
    def test_without_endpoint(self, consumer):
        with patch("boto3.client") as mock_client:
            consumer._create_sqs_client()
        mock_client.assert_called_once_with("sqs", region_name="us-east-1")

    def test_with_endpoint(self, indexer):
        consumer = SQSConsumer(
            indexer=indexer, queue_url=QUEUE_URL, region="eu-west-1", endpoint_url="http://localstack:4566"
        )
        with patch("boto3.client") as mock_client:
            consumer._create_sqs_client()
        mock_client.assert_called_once_with(
            "sqs", region_name="eu-west-1", endpoint_url="http://localstack:4566"
        )


class TestPollLoop:
    def test_processes_received_messages(self, consumer):
        sqs = MagicMock()
        messages = [_message({"action": "noop"}, "a"), _message({"action": "noop"}, "b")]

        def receive(**kwargs):
            consumer._running = False
            return {"Messages": messages}

        sqs.receive_message.side_effect = receive
        consumer._running = True
        with patch.object(consumer, "_create_sqs_client", return_value=sqs), \
                patch.object(consumer, "_process_message") as process:
            consumer._poll_loop()

        sqs.receive_message.assert_called_once_with(
            QueueUrl=QUEUE_URL, MaxNumberOfMessages=10, WaitTimeSeconds=0, VisibilityTimeout=60
        )
        assert [c.args[1] for c in process.call_args_list] == messages

    def test_empty_response(self, consumer):
        sqs = MagicMock()

        def receive(**kwargs):
            consumer._running = False
            return {}

        sqs.receive_message.side_effect = receive
        consumer._running = True
        with patch.object(consumer, "_create_sqs_client", return_value=sqs), \
                patch.object(consumer, "_process_message") as process:
            consumer._poll_loop()
        process.assert_not_called()

    def test_receive_error_backs_off(self, consumer):
        sqs = MagicMock()

        def receive(**kwargs):
            consumer._running = False
            raise RuntimeError("boom")

        sqs.receive_message.side_effect = receive
        consumer._running = True
        with patch.object(consumer, "_create_sqs_client", return_value=sqs), \
                patch("app.services.sqs_consumer.time.sleep") as sleep:
            consumer._poll_loop()
        sleep.assert_called_once_with(5)

    def test_not_running_does_not_poll(self, consumer):
        sqs = MagicMock()
        with patch.object(consumer, "_create_sqs_client", return_value=sqs):
            consumer._poll_loop()
        sqs.receive_message.assert_not_called()


class TestNormalizeEvent:
    @pytest.mark.parametrize(
        ("event_type", "action"),
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
    def test_snake_case_nested(self, event_type, action):
        payload = {"id": "x"}
        result = SQSConsumer._normalize_event({"event_type": event_type, "payload": payload})
        assert result == {"action": action, "data": payload}

    def test_snake_case_unknown_event_passes_through_as_action(self):
        result = SQSConsumer._normalize_event({"event_type": "document_shared", "payload": {}})
        assert result == {"action": "document_shared", "data": {}}

    @pytest.mark.parametrize("event_type", ["file_uploaded", "file_created", "file_updated", "file_restored"])
    def test_camel_case_index(self, event_type):
        body = {
            "eventType": event_type,
            "fileId": "f-1",
            "name": "report.pdf",
            "mimeType": "application/pdf",
            "ownerId": "u-1",
            "folderId": "fold-1",
            "sizeBytes": 42,
            "tags": ["q1"],
            "timestamp": "2026-01-01T00:00:00Z",
        }
        assert SQSConsumer._normalize_event(body) == {
            "action": "index_file",
            "data": {
                "id": "f-1",
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "owner_id": "u-1",
                "folder_id": "fold-1",
                "size": 42,
                "tags": ["q1"],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        }

    def test_camel_case_defaults(self):
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
    def test_camel_case_delete(self, event_type):
        result = SQSConsumer._normalize_event({"eventType": event_type, "fileId": "f-9"})
        assert result == {"action": "delete", "data": {"type": "file", "id": "f-9"}}

    @pytest.mark.parametrize("event_type", ["file_shared", "file_moved"])
    def test_camel_case_unindexable_returned_unchanged(self, event_type):
        body = {"eventType": event_type, "fileId": "f-1"}
        assert SQSConsumer._normalize_event(body) is body

    def test_indexer_format_passthrough(self):
        body = {"action": "index_document", "data": {"id": "d"}}
        assert SQSConsumer._normalize_event(body) is body


class TestProcessMessage:
    def test_direct_message_processed_and_deleted(self, consumer, indexer):
        sqs = MagicMock()
        body = {"action": "index_document", "data": {"id": "d-1", "title": "T"}}
        consumer._process_message(sqs, _message(body))
        indexer.process_event.assert_called_once_with(body)
        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-1")

    def test_sns_wrapped_message_unwrapped_and_normalized(self, consumer, indexer):
        sqs = MagicMock()
        inner = {"eventType": "file_deleted", "fileId": "f-1"}
        wrapper = {"TopicArn": "arn:aws:sns:us-east-1:0:file-events", "Message": json.dumps(inner)}
        consumer._process_message(sqs, _message(wrapper))
        indexer.process_event.assert_called_once_with(
            {"action": "delete", "data": {"type": "file", "id": "f-1"}}
        )
        sqs.delete_message.assert_called_once()

    def test_message_without_topic_arn_not_unwrapped(self, consumer, indexer):
        sqs = MagicMock()
        body = {"Message": "not-json"}
        consumer._process_message(sqs, _message(body))
        indexer.process_event.assert_called_once_with(body)

    def test_invalid_json_deleted(self, consumer, indexer):
        sqs = MagicMock()
        consumer._process_message(sqs, _message("{not json"))
        indexer.process_event.assert_not_called()
        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-1")

    def test_invalid_sns_inner_json_deleted(self, consumer, indexer):
        sqs = MagicMock()
        wrapper = {"TopicArn": "arn", "Message": "{broken"}
        consumer._process_message(sqs, _message(wrapper))
        indexer.process_event.assert_not_called()
        sqs.delete_message.assert_called_once()

    def test_validation_error_deleted(self, consumer, indexer):
        sqs = MagicMock()
        indexer.process_event.side_effect = ValueError("Document 'id' is required")
        consumer._process_message(sqs, _message({"action": "index_document", "data": {}}))
        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-1")

    def test_unexpected_error_leaves_message_for_retry(self, consumer, indexer):
        sqs = MagicMock()
        indexer.process_event.side_effect = RuntimeError("meilisearch down")
        consumer._process_message(sqs, _message({"action": "index_document", "data": {}}))
        sqs.delete_message.assert_not_called()

    def test_missing_body_and_receipt_defaults(self, consumer, indexer):
        sqs = MagicMock()
        consumer._process_message(sqs, {})
        indexer.process_event.assert_called_once_with({})
        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="")
