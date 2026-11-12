"""S3 bucket-ownership checks in the ETL scripts (python:S7608).

Run: python -m unittest discover -s etl/tests
"""
import configparser
import importlib.util
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

import boto3
from botocore.stub import ANY, Stubber

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
OWNER = "111122223333"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config_reader(owner):
    def read(self, *_args, **_kwargs):
        self.read_dict({
            "aws": {"access_key": "x", "secret_key": "x", "region": "us-east-1"},
            "s3": {
                "file_storage_bucket": "files",
                "quarantine_bucket": "quarantine",
                "data_lake_bucket": "lake",
                "archive_bucket": "archive",
                "expected_bucket_owner": owner,
            },
        })
    return read


class FakeTable:
    def __init__(self, items):
        self.items = items

    def scan(self, **_kwargs):
        return {"Items": self.items}

    def batch_writer(self):
        return mock.MagicMock()


def run(script, owner, s3_stub_setup, table_items):
    s3 = boto3.client("s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    resource = mock.Mock()
    resource.Table.return_value = FakeTable(table_items)
    with Stubber(s3) as stub, \
            mock.patch.object(configparser.ConfigParser, "read", config_reader(owner)), \
            mock.patch("boto3.client", return_value=s3), \
            mock.patch("boto3.resource", return_value=resource):
        s3_stub_setup(stub)
        load_script(script).main()
        stub.assert_no_pending_responses()


class StorageCleanupTest(unittest.TestCase):
    referenced = [{"s3_key": "files/keep.pdf"}]

    def list_response(self, stub):
        now = datetime.now(tz=timezone.utc)
        stub.add_response(
            "list_objects_v2",
            {"Contents": [
                {"Key": "files/keep.pdf", "Size": 1, "LastModified": now},
                {"Key": "files/orphan.pdf", "Size": 1, "LastModified": now},
            ]},
            {"Bucket": "files", "Prefix": "files/", "ExpectedBucketOwner": OWNER},
        )

    def copy_params(self):
        return {
            "Bucket": "quarantine", "Key": ANY, "ExpectedBucketOwner": OWNER,
            "CopySource": {"Bucket": "files", "Key": "files/orphan.pdf"},
            "ExpectedSourceBucketOwner": OWNER, "MetadataDirective": "COPY",
        }

    def report_put(self, stub):
        stub.add_response(
            "put_object", {},
            {"Bucket": "lake", "Key": ANY, "Body": ANY, "ExpectedBucketOwner": OWNER},
        )

    def test_every_s3_call_sends_expected_bucket_owner(self):
        def setup(stub):
            self.list_response(stub)
            stub.add_response("copy_object", {}, self.copy_params())
            stub.add_response(
                "delete_object", {},
                {"Bucket": "files", "Key": "files/orphan.pdf", "ExpectedBucketOwner": OWNER},
            )
            self.report_put(stub)
        run("storage_cleanup_daily", OWNER, setup, self.referenced)

    def test_rejected_quarantine_copy_does_not_delete_source(self):
        def setup(stub):
            self.list_response(stub)
            stub.add_client_error("copy_object", "AccessDenied", http_status_code=403,
                                  expected_params=self.copy_params())
            self.report_put(stub)  # no delete_object queued: a call would fail the stub
        run("storage_cleanup_daily", OWNER, setup, self.referenced)

    def test_missing_or_invalid_owner_fails_before_any_s3_call(self):
        for owner in ("", "  ", "not-an-account", "12345"):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                run("storage_cleanup_daily", owner, lambda stub: None, self.referenced)


class AuditArchiveTest(unittest.TestCase):
    def test_archive_and_report_send_expected_bucket_owner(self):
        def setup(stub):
            stub.add_response(
                "put_object", {},
                {"Bucket": "archive", "Key": ANY, "Body": ANY,
                 "ExpectedBucketOwner": OWNER, "StorageClass": "GLACIER"},
            )
            stub.add_response(
                "put_object", {},
                {"Bucket": "archive", "Key": ANY, "Body": ANY, "ExpectedBucketOwner": OWNER},
            )
        events = [{"event_id": "e1", "timestamp": "2026-01-01T00:00:00Z"}]
        run("audit_archive_weekly", OWNER, setup, events)

if __name__ == "__main__":
    unittest.main()
