import os
import sys
import unittest

import boto3
from botocore.stub import Stubber

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from sqs_ack import load_then_ack  # noqa: E402

QUEUE = "https://sqs.us-east-1.amazonaws.com/123456789012/otterworks-analytics"
RECEIPTS = [{"Id": str(i), "ReceiptHandle": "rh-%d" % i} for i in range(12)]


def _sqs():
    client = boto3.client(
        "sqs", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
    )
    return client, Stubber(client)


class UploadFailed(Exception):
    pass


def _fail():
    raise UploadFailed("s3 put_object denied")


class LoadThenAckTest(unittest.TestCase):
    def test_deletes_receipts_in_batches_after_successful_load(self):
        client, stub = _sqs()
        for chunk in (RECEIPTS[:10], RECEIPTS[10:]):
            stub.add_response(
                "delete_message_batch",
                {"Successful": [{"Id": e["Id"]} for e in chunk], "Failed": []},
                {"QueueUrl": QUEUE, "Entries": chunk},
            )
        loaded = []
        with stub:
            load_then_ack(client, QUEUE, RECEIPTS, lambda: loaded.append(True))
        self.assertEqual(loaded, [True])
        stub.assert_no_pending_responses()

    def test_failed_load_releases_receipts_and_never_deletes(self):
        client, stub = _sqs()
        for chunk in (RECEIPTS[:10], RECEIPTS[10:]):
            stub.add_response(
                "change_message_visibility_batch",
                {"Successful": [{"Id": e["Id"]} for e in chunk], "Failed": []},
                {"QueueUrl": QUEUE, "Entries": [dict(e, VisibilityTimeout=0) for e in chunk]},
            )
        with stub, self.assertRaises(UploadFailed):
            load_then_ack(client, QUEUE, RECEIPTS, _fail)
        stub.assert_no_pending_responses()

    def test_release_failure_still_raises_the_load_error(self):
        client, stub = _sqs()
        stub.add_client_error("change_message_visibility_batch", "AWS.SimpleQueueService.NonExistentQueue")
        with stub, self.assertRaises(UploadFailed):
            load_then_ack(client, QUEUE, RECEIPTS, _fail)


if __name__ == "__main__":
    unittest.main()
