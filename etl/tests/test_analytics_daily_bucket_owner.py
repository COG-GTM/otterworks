"""Regression tests for S3 bucket-ownership checks in analytics_daily.py.

Run: python3 -m unittest discover -s etl/tests
"""
import configparser
import importlib.util
import json
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest import mock

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "analytics_daily.py")
CONFIG = os.path.join(os.path.dirname(__file__), "..", "config.ini")
_read_config = configparser.ConfigParser.read

try:
    import pandas  # noqa: F401
    HAVE_PANDAS = True
except ImportError:
    HAVE_PANDAS = False


def load_module():
    stubs = {"boto3": mock.MagicMock(), "psycopg2": types.ModuleType("psycopg2")}
    if not HAVE_PANDAS:
        stubs["pandas"] = mock.MagicMock()
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("analytics_daily", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def make_config(account_id):
    config = configparser.ConfigParser()
    _read_config(config, CONFIG)
    if account_id is None:
        config.remove_option("aws", "account_id")
    else:
        config.set("aws", "account_id", account_id)
    return config


class GetExpectedBucketOwnerTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_accepts_twelve_digit_account_id(self):
        self.assertEqual(self.module.get_expected_bucket_owner(make_config(" 123456789012 ")), "123456789012")

    def test_rejects_missing_or_malformed_account_id(self):
        for value in (None, "", "12345678901", "1234567890123", "12345678901a", "\uff11" * 12):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module.get_expected_bucket_owner(make_config(value))


class MainBucketOwnerTest(unittest.TestCase):
    def run_main(self, account_id):
        module = load_module()
        ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")  # noqa: UP017 - matches the py3.7-era script
        sqs = mock.MagicMock()
        sqs.receive_message.side_effect = [
            {"Messages": [{
                "MessageId": "m1",
                "ReceiptHandle": "r1",
                "Body": json.dumps({"event_type": "document_created", "user_id": "u1",
                                    "resource_id": "d1", "timestamp": ds + "T10:00:00Z"}),
            }]},
            {"Messages": []},
        ]
        s3 = mock.MagicMock()
        boto3 = mock.MagicMock()
        boto3.client.side_effect = lambda service, **kw: {"sqs": sqs, "s3": s3}[service]
        boto3.resource.return_value.Table.return_value.scan.return_value = {"Items": []}
        psycopg2 = mock.MagicMock()
        psycopg2.connect.side_effect = RuntimeError("no database in tests")

        def read(config, filenames, encoding=None):
            parsed = make_config(account_id)
            config.read_dict({s: dict(parsed.items(s, raw=True)) for s in parsed.sections()})
            return [CONFIG]

        with mock.patch.object(module, "boto3", boto3), mock.patch.object(module, "psycopg2", psycopg2), \
                mock.patch.object(configparser.ConfigParser, "read", read), mock.patch("builtins.print"):
            try:
                module.main()
                error = None
            except ValueError as e:
                error = e
        return error, boto3, sqs, s3

    def test_invalid_account_id_fails_before_any_aws_call(self):
        error, boto3, sqs, s3 = self.run_main("not-an-account")
        self.assertIsInstance(error, ValueError)
        boto3.client.assert_not_called()
        sqs.delete_message_batch.assert_not_called()
        s3.put_object.assert_not_called()

    @unittest.skipUnless(HAVE_PANDAS, "pandas is required to run the aggregation")
    def test_every_upload_sets_expected_bucket_owner(self):
        error, _, _, s3 = self.run_main("210987654321")
        self.assertIsNone(error)
        keys = [c.kwargs["Key"] for c in s3.put_object.call_args_list]
        self.assertEqual(len(keys), 4, keys)
        for c in s3.put_object.call_args_list:
            self.assertEqual(c.kwargs.get("ExpectedBucketOwner"), "210987654321", c.kwargs["Key"])


if __name__ == "__main__":
    unittest.main()
