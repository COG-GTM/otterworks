import configparser
import importlib.util
import pathlib
import unittest
from datetime import datetime, timezone
from unittest import mock

import boto3
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "storage_cleanup_daily.py"
spec = importlib.util.spec_from_file_location("storage_cleanup_daily", SCRIPT)
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)

OWNER = "111122223333"
CONFIG = """
[aws]
access_key = test
secret_key = test
region = us-east-1
[s3]
data_lake_bucket = lake
file_storage_bucket = files
quarantine_bucket = quarantine
expected_bucket_owner = %s
"""


class FakeTable:
    def scan(self, **_):
        return {"Items": [{"s3_key": "files/kept.txt"}]}


class FakeDynamo:
    def Table(self, _):
        return FakeTable()


def s3_client():
    return boto3.client("s3", region_name="us-east-1", aws_access_key_id="t", aws_secret_access_key="t")


def run_job(clients, owner=OWNER, env=None):
    def fake_read(self, _path):
        self.read_string(CONFIG % owner)

    queue = list(clients)
    with mock.patch.object(configparser.ConfigParser, "read", fake_read), \
         mock.patch.object(job.boto3, "client", side_effect=lambda *a, **k: queue.pop(0)), \
         mock.patch.object(job.boto3, "resource", return_value=FakeDynamo()), \
         mock.patch.dict(job.os.environ, {"S3_EXPECTED_BUCKET_OWNER": "", **(env or {})}):
        job.main()


def listing():
    now = datetime.now(tz=timezone.utc)
    return {"Contents": [
        {"Key": "files/kept.txt", "Size": 1, "LastModified": now},
        {"Key": "files/orphan.txt", "Size": 2, "LastModified": now},
    ]}


class ExpectedBucketOwnerTest(unittest.TestCase):
    def setUp(self):
        self.sts = boto3.client("sts", region_name="us-east-1", aws_access_key_id="t", aws_secret_access_key="t")
        self.s3 = s3_client()
        self.report = s3_client()

    def test_every_s3_call_pins_the_bucket_owner(self):
        with Stubber(self.s3) as s3, Stubber(self.report) as report:
            s3.add_response("list_objects_v2", listing(),
                            {"Bucket": "files", "Prefix": "files/", "ExpectedBucketOwner": OWNER})
            s3.add_response("copy_object", {}, {
                "Bucket": "quarantine", "Key": ANY,
                "CopySource": {"Bucket": "files", "Key": "files/orphan.txt"},
                "MetadataDirective": "COPY",
                "ExpectedBucketOwner": OWNER, "ExpectedSourceBucketOwner": OWNER,
            })
            s3.add_response("delete_object", {},
                            {"Bucket": "files", "Key": "files/orphan.txt", "ExpectedBucketOwner": OWNER})
            report.add_response("put_object", {},
                                {"Bucket": "lake", "Key": ANY, "Body": ANY, "ExpectedBucketOwner": OWNER})
            run_job([self.sts, self.s3, self.report])
            s3.assert_no_pending_responses()
            report.assert_no_pending_responses()

    def test_foreign_quarantine_bucket_never_deletes_source(self):
        with Stubber(self.s3) as s3, Stubber(self.report) as report:
            s3.add_response("list_objects_v2", listing(), {"Bucket": "files", "Prefix": "files/", "ExpectedBucketOwner": OWNER})
            s3.add_client_error("copy_object", service_error_code="AccessDenied", http_status_code=403)
            report.add_response("put_object", {}, {"Bucket": "lake", "Key": ANY, "Body": ANY, "ExpectedBucketOwner": OWNER})
            attempted = []
            self.s3.meta.events.register(
                "provide-client-params.s3.*", lambda model, **_: attempted.append(model.name)
            )
            run_job([self.sts, self.s3, self.report])
            s3.assert_no_pending_responses()
            self.assertEqual(attempted, ["ListObjectsV2", "CopyObject"])

    def test_foreign_file_bucket_aborts_before_any_change(self):
        with Stubber(self.s3) as s3:
            s3.add_client_error("list_objects_v2", service_error_code="AccessDenied", http_status_code=403)
            with self.assertRaises(ClientError):
                run_job([self.sts, self.s3])

    def test_defaults_to_caller_account(self):
        with Stubber(self.sts) as sts:
            sts.add_response("get_caller_identity", {"Account": "444455556666", "Arn": "arn:aws:iam::444455556666:user/etl", "UserId": "AIDA"})
            cfg = configparser.ConfigParser()
            cfg.read_string(CONFIG % "")
            with mock.patch.dict(job.os.environ, {"S3_EXPECTED_BUCKET_OWNER": ""}):
                self.assertEqual(job.resolve_expected_bucket_owner(cfg, self.sts), "444455556666")

    def test_env_overrides_config(self):
        cfg = configparser.ConfigParser()
        cfg.read_string(CONFIG % OWNER)
        with mock.patch.dict(job.os.environ, {"S3_EXPECTED_BUCKET_OWNER": "999988887777"}):
            self.assertEqual(job.resolve_expected_bucket_owner(cfg, self.sts), "999988887777")

    def test_rejects_malformed_owner(self):
        cfg = configparser.ConfigParser()
        cfg.read_string(CONFIG % "not-an-account")
        with mock.patch.dict(job.os.environ, {"S3_EXPECTED_BUCKET_OWNER": ""}), self.assertRaises(ValueError):
            job.resolve_expected_bucket_owner(cfg, self.sts)


if __name__ == "__main__":
    unittest.main()
