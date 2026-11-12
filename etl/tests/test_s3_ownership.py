import configparser
import io
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

import boto3
from botocore.stub import ANY, Stubber

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import s3_ownership  # noqa: E402
import storage_cleanup_daily  # noqa: E402

OWNER = "111122223333"


def _config(owner=None):
    config = configparser.ConfigParser()
    config.read_string(
        "[aws]\naccess_key = AKIATEST\nsecret_key = test\nregion = us-east-1\n"
        "[s3]\nfile_storage_bucket = files\nquarantine_bucket = quarantine\n"
        "data_lake_bucket = lake\n" + ("expected_bucket_owner = %s\n" % owner if owner else "")
    )
    return config


def _client(service):
    return boto3.client(
        service, region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
    )


class ResolveExpectedBucketOwnerTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(s3_ownership.ENV_VAR, None)

    def test_env_wins_over_config(self):
        os.environ[s3_ownership.ENV_VAR] = "999988887777"
        self.assertEqual(
            s3_ownership.resolve_expected_bucket_owner(_config(OWNER), "a", "b", "us-east-1"),
            "999988887777",
        )

    def test_config_value(self):
        self.assertEqual(
            s3_ownership.resolve_expected_bucket_owner(_config(OWNER), "a", "b", "us-east-1"),
            OWNER,
        )

    def test_falls_back_to_sts_caller_account(self):
        sts = _client("sts")
        with Stubber(sts) as stub, mock.patch.object(s3_ownership.boto3, "client", return_value=sts):
            stub.add_response(
                "get_caller_identity",
                {"Account": "444455556666", "Arn": "arn:aws:iam::444455556666:user/etl", "UserId": "AIDA"},
            )
            self.assertEqual(
                s3_ownership.resolve_expected_bucket_owner(_config(), "a", "b", "us-east-1"),
                "444455556666",
            )

    def test_rejects_non_account_id(self):
        with self.assertRaises(ValueError):
            s3_ownership.resolve_expected_bucket_owner(_config("not-an-account"), "a", "b", "us-east-1")


class StorageCleanupBucketOwnerTest(unittest.TestCase):
    def test_every_s3_call_carries_expected_bucket_owner(self):
        os.environ.pop(s3_ownership.ENV_VAR, None)
        s3 = _client("s3")
        dynamodb = boto3.resource(
            "dynamodb", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
        )
        now = datetime.now(tz=timezone.utc)
        ds = now.strftime("%Y-%m-%d")

        with Stubber(s3) as s3_stub, Stubber(dynamodb.meta.client) as ddb_stub:
            s3_stub.add_response(
                "list_objects_v2",
                {"Contents": [
                    {"Key": "files/kept", "Size": 10, "LastModified": now},
                    {"Key": "files/orphan", "Size": 20, "LastModified": now},
                ]},
                {"Bucket": "files", "Prefix": "files/", "ExpectedBucketOwner": OWNER},
            )
            ddb_stub.add_response(
                "scan",
                {"Items": [{"s3_key": {"S": "files/kept"}}]},
                {"TableName": "otterworks-file-metadata", "ProjectionExpression": "s3_key"},
            )
            s3_stub.add_response(
                "copy_object",
                {},
                {
                    "Bucket": "quarantine",
                    "Key": "quarantined/%s/files/orphan" % ds,
                    "CopySource": {"Bucket": "files", "Key": "files/orphan"},
                    "MetadataDirective": "COPY",
                    "ExpectedBucketOwner": OWNER,
                    "ExpectedSourceBucketOwner": OWNER,
                },
            )
            s3_stub.add_response(
                "delete_object",
                {},
                {"Bucket": "files", "Key": "files/orphan", "ExpectedBucketOwner": OWNER},
            )
            s3_stub.add_response(
                "put_object",
                {},
                {
                    "Bucket": "lake",
                    "Key": "reports/storage-cleanup/%s/report.json" % ds,
                    "Body": ANY,
                    "ExpectedBucketOwner": OWNER,
                },
            )

            config = _config(OWNER)
            with mock.patch.object(storage_cleanup_daily.configparser, "ConfigParser", return_value=config), \
                    mock.patch.object(config, "read"), \
                    mock.patch.object(storage_cleanup_daily.boto3, "client", return_value=s3), \
                    mock.patch.object(storage_cleanup_daily.boto3, "resource", return_value=dynamodb), \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                storage_cleanup_daily.main()

            s3_stub.assert_no_pending_responses()
            ddb_stub.assert_no_pending_responses()
            self.assertIn("Quarantined 1 objects (0 failed)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
