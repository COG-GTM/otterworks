"""Tests for ExpectedBucketOwner enforcement in user_activity_daily.py.

Run: python3 -m unittest discover -s etl/tests
boto3 and psycopg2 are replaced with mocks, so only the standard library is needed.
"""
import configparser
import datetime
import gzip
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "user_activity_daily.py"


def load_module():
    fake_boto3 = mock.MagicMock()
    fake_psycopg2 = mock.MagicMock()
    with mock.patch.dict(sys.modules, {"boto3": fake_boto3, "psycopg2": fake_psycopg2}):
        spec = importlib.util.spec_from_file_location("user_activity_daily", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def make_config(owner=""):
    config = configparser.ConfigParser()
    config.read_string(
        "[aws]\naccess_key = k\nsecret_key = s\nregion = us-east-1\n"
        "[database]\nhost = h\nport = 5432\ndatabase = d\nuser = u\npassword = p\n"
        "[s3]\ndata_lake_bucket = otterworks-data-lake\nexpected_bucket_owner = %s\n" % owner
    )
    return config


def sts_factory(account="111111111111"):
    sts = mock.MagicMock()
    sts.get_caller_identity.return_value = {"Account": account}
    return mock.MagicMock(return_value=sts)


class ResolveExpectedBucketOwnerTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("ETL_EXPECTED_BUCKET_OWNER", None)

    def test_env_overrides_config_and_sts(self):
        os.environ["ETL_EXPECTED_BUCKET_OWNER"] = "333333333333"
        factory = sts_factory()
        owner = self.mod.resolve_expected_bucket_owner(make_config("222222222222"), factory)
        self.assertEqual(owner, "333333333333")
        factory.assert_not_called()

    def test_config_used_when_env_unset(self):
        factory = sts_factory()
        owner = self.mod.resolve_expected_bucket_owner(make_config("222222222222"), factory)
        self.assertEqual(owner, "222222222222")
        factory.assert_not_called()

    def test_falls_back_to_caller_account(self):
        owner = self.mod.resolve_expected_bucket_owner(make_config(""), sts_factory("111111111111"))
        self.assertEqual(owner, "111111111111")

    def test_missing_config_key_falls_back_to_caller_account(self):
        config = make_config()
        config.remove_option("s3", "expected_bucket_owner")
        owner = self.mod.resolve_expected_bucket_owner(config, sts_factory("111111111111"))
        self.assertEqual(owner, "111111111111")

    def test_rejects_non_account_ids(self):
        for bad in ("otterworks", "12345", "1234567890123", "12345678901a"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.mod.resolve_expected_bucket_owner(make_config(bad), sts_factory())

    def test_rejects_invalid_env_value(self):
        os.environ["ETL_EXPECTED_BUCKET_OWNER"] = "not-an-account"
        with self.assertRaises(ValueError):
            self.mod.resolve_expected_bucket_owner(make_config("222222222222"), sts_factory())


class MainS3CallsTest(unittest.TestCase):
    def run_main(self, owner_in_config):
        mod = load_module()
        s3 = mock.MagicMock()
        blob = gzip.compress(b'{"user_id": "u1", "total": 5, "actions": {"edit": 5}}\n')
        s3.get_object.side_effect = lambda **kw: {"Body": mock.MagicMock(read=mock.MagicMock(return_value=blob))}
        sts = mock.MagicMock()
        sts.get_caller_identity.return_value = {"Account": "111111111111"}
        mod.boto3.client.side_effect = lambda service, **kw: sts if service == "sts" else s3

        cursor = mock.MagicMock()
        cursor.fetchall.return_value = [(datetime.date(2026, 11, 1), 3, 2, 1, 10, 1, 2, 3, 1, 1, 0, 100)]
        mod.psycopg2.connect.return_value.cursor.return_value = cursor

        config = make_config(owner_in_config)
        with mock.patch.object(mod.configparser, "ConfigParser", return_value=config), \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("builtins.print"):
            os.environ.pop("ETL_EXPECTED_BUCKET_OWNER", None)
            mod.main()
        return s3

    def assert_all_calls_carry_owner(self, s3, owner):
        self.assertEqual(s3.get_object.call_count, 30)
        for call in s3.get_object.call_args_list:
            self.assertEqual(call.kwargs["ExpectedBucketOwner"], owner)
        keys = [c.kwargs["Key"] for c in s3.put_object.call_args_list]
        self.assertEqual(len(keys), 3)
        self.assertTrue(any(k.endswith("/latest/activity_report.json") for k in keys))
        self.assertTrue(any(k.endswith("/user_summaries.jsonl") for k in keys))
        for call in s3.put_object.call_args_list:
            self.assertEqual(call.kwargs["ExpectedBucketOwner"], owner)

    def test_reads_and_writes_send_configured_owner(self):
        self.assert_all_calls_carry_owner(self.run_main("222222222222"), "222222222222")

    def test_reads_and_writes_send_caller_account_by_default(self):
        self.assert_all_calls_carry_owner(self.run_main(""), "111111111111")

    def test_invalid_owner_exits_before_any_s3_call(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_main("otterworks")
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
