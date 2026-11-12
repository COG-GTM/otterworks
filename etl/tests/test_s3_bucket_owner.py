"""Every S3 request made by the ETL jobs must pin the bucket owner account.

Runs each job's real main() with real botocore; S3 HTTP is answered by a fake
that, like AWS, returns 403 when x-amz-(source-)expected-bucket-owner does not
match the bucket owner. SQS, DynamoDB and PostgreSQL are mocked.

    pip install -r etl/requirements.txt && python -m unittest discover etl/tests
"""
import configparser
import contextlib
import gzip
import io
import json
import os
import re
import sys
import types
import unittest
from unittest import mock

import boto3
import botocore.awsrequest
from botocore.exceptions import ClientError

try:
    import psycopg2
except ImportError:  # the DB is mocked; the driver is not needed to run these tests
    psycopg2 = sys.modules["psycopg2"] = types.ModuleType("psycopg2")

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.ini")
S3_JOBS = ["analytics_daily", "audit_archive_weekly", "storage_cleanup_daily", "user_activity_daily"]
OWNER = "123456789012"
OTHER_ACCOUNT = "999999999999"


class _Body:
    def __init__(self, data):
        self._buf = io.BytesIO(data)

    def stream(self, **_):
        yield self._buf.getvalue()

    def read(self, *args, **_):
        return self._buf.read(*args)

    def close(self):
        pass


class FakeS3:
    def __init__(self, bucket_owner):
        self.bucket_owner = bucket_owner
        self.requests = []

    def __call__(self, request, **_):
        headers = {k.lower(): v.decode() if isinstance(v, bytes) else v for k, v in request.headers.items()}
        self.requests.append((request.method, request.url, headers))
        for header in ("x-amz-expected-bucket-owner", "x-amz-source-expected-bucket-owner"):
            if header in headers and headers[header] != self.bucket_owner:
                return self._respond(request, 403, b"<Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>")
        if request.method == "GET" and "list-type=2" in request.url:
            return self._respond(request, 200, (
                b"<ListBucketResult><IsTruncated>false</IsTruncated>"
                b"<Contents><Key>files/orphan.bin</Key><Size>10</Size><LastModified>2026-01-01T00:00:00Z</LastModified></Contents>"
                b"<Contents><Key>files/kept.bin</Key><Size>20</Size><LastModified>2026-01-01T00:00:00Z</LastModified></Contents></ListBucketResult>"))
        if request.method == "GET":
            return self._respond(request, 200, gzip.compress(b'{"user_id": "u1", "event_count": 3}\n'))
        if "x-amz-copy-source" in headers:
            return self._respond(request, 200, b"<CopyObjectResult><ETag>\"e\"</ETag></CopyObjectResult>")
        return self._respond(request, 204 if request.method == "DELETE" else 200, b"")

    @staticmethod
    def _respond(request, status, body):
        return botocore.awsrequest.AWSResponse(request.url, status, {}, _Body(body))


def run_job(name, fake_s3, owner_setting=OWNER):
    parser = configparser.ConfigParser()
    parser.read(CONFIG_PATH)
    if owner_setting is None:
        parser.remove_option("s3", "expected_bucket_owner")
    else:
        parser.set("s3", "expected_bucket_owner", owner_setting)

    real_client = boto3.client

    def client(service, **_):
        if service == "s3":
            s3 = real_client("s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y")
            s3.meta.events.register("before-send.s3", fake_s3)
            return s3
        sqs = mock.MagicMock()
        message = {"Body": json.dumps({"eventType": "document_created", "userId": "u1", "documentId": "d1",
                                        "timestamp": "2026-01-01T10:00:00Z"}), "MessageId": "1", "ReceiptHandle": "r"}
        sqs.receive_message.side_effect = [{"Messages": [message]}, {"Messages": []}]
        return sqs

    def resource(service, **_):
        dynamodb = mock.MagicMock()
        dynamodb.Table.return_value.scan.return_value = {"Items": [{
            "s3_key": "files/kept.bin", "event_id": "e1", "timestamp": "2020-01-01",
            "eventType": "file_uploaded", "userId": "u1", "fileId": "f1", "sizeBytes": 5}]}
        return dynamodb

    connect = mock.MagicMock()
    connect.return_value.cursor.return_value.fetchall.return_value = []

    path = os.path.join(SCRIPTS_DIR, name + ".py")
    namespace = {"__name__": "etl_" + name, "__file__": path}
    with mock.patch.object(boto3, "client", client), mock.patch.object(boto3, "resource", resource), \
            mock.patch.object(psycopg2, "connect", connect, create=True), \
            mock.patch.object(configparser.ConfigParser, "read",
                              lambda self, *_a, **_k: self.read_dict({s: dict(parser[s]) for s in parser.sections()})), \
            contextlib.redirect_stdout(io.StringIO()):
        exec(compile(open(path).read(), path, "exec"), namespace)
        namespace["main"]()


class ExpectedBucketOwnerTest(unittest.TestCase):
    def test_every_s3_request_pins_the_owner(self):
        for name in S3_JOBS:
            with self.subTest(job=name):
                fake_s3 = FakeS3(bucket_owner=OWNER)
                run_job(name, fake_s3)
                self.assertTrue(fake_s3.requests)
                for method, url, headers in fake_s3.requests:
                    self.assertEqual(headers.get("x-amz-expected-bucket-owner"), OWNER, "%s %s" % (method, url))
                    if "x-amz-copy-source" in headers:
                        self.assertEqual(headers.get("x-amz-source-expected-bucket-owner"), OWNER, url)

    def test_quarantine_copy_pins_source_owner(self):
        fake_s3 = FakeS3(bucket_owner=OWNER)
        run_job("storage_cleanup_daily", fake_s3)
        copies = [h for _, _, h in fake_s3.requests if "x-amz-copy-source" in h]
        self.assertEqual(len(copies), 1)

    def test_bucket_owned_by_another_account_is_refused(self):
        for name in S3_JOBS:
            with self.subTest(job=name):
                fake_s3 = FakeS3(bucket_owner=OTHER_ACCOUNT)
                with self.assertRaises(ClientError) as raised:
                    run_job(name, fake_s3)
                self.assertEqual(raised.exception.response["Error"]["Code"], "AccessDenied")
                writes = [r for r in fake_s3.requests if r[0] in ("PUT", "DELETE")]
                self.assertLessEqual(len(writes), 1)

    def test_invalid_or_missing_owner_stops_before_any_s3_call(self):
        for name in S3_JOBS:
            for setting in ("not-an-id", "12345", ""):
                with self.subTest(job=name, setting=setting):
                    fake_s3 = FakeS3(bucket_owner=OWNER)
                    with self.assertRaises(SystemExit):
                        run_job(name, fake_s3, owner_setting=setting)
                    self.assertEqual(fake_s3.requests, [])
            with self.subTest(job=name, setting=None):
                fake_s3 = FakeS3(bucket_owner=OWNER)
                with self.assertRaises(configparser.NoOptionError):
                    run_job(name, fake_s3, owner_setting=None)
                self.assertEqual(fake_s3.requests, [])

    def test_config_ships_a_well_formed_owner(self):
        parser = configparser.ConfigParser()
        parser.read(CONFIG_PATH)
        self.assertRegex(parser.get("s3", "expected_bucket_owner"), re.compile(r"^\d{12}$"))


if __name__ == "__main__":
    unittest.main()
