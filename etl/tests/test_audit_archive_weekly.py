import configparser
import importlib.util
import pathlib
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "audit_archive_weekly.py"
_spec = importlib.util.spec_from_file_location("audit_archive_weekly", SCRIPT)
aaw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aaw)

CALLER_ACCOUNT = "123456789012"
CONFIG = """
[aws]
access_key = test
secret_key = test
region = us-east-1
[s3]
archive_bucket = otterworks-audit-archive
archive_bucket_owner = %s
"""


def make_config(owner=""):
    config = configparser.ConfigParser()
    config.read_string(CONFIG % owner)
    return config


def make_sts():
    sts = mock.Mock()
    sts.get_caller_identity.return_value = {"Account": CALLER_ACCOUNT}
    return sts


class ResolveBucketOwnerTest(unittest.TestCase):
    def test_defaults_to_caller_account(self):
        sts = make_sts()
        self.assertEqual(aaw.resolve_bucket_owner(make_config(), sts), CALLER_ACCOUNT)
        sts.get_caller_identity.assert_called_once()

    def test_configured_owner_wins(self):
        sts = make_sts()
        self.assertEqual(aaw.resolve_bucket_owner(make_config("111122223333"), sts), "111122223333")
        sts.get_caller_identity.assert_not_called()

    def test_rejects_non_account_id(self):
        for bad in ("abc", "12345", "1234567890123", "arn:aws:iam::123456789012:root"):
            with self.subTest(owner=bad), self.assertRaises(ValueError):
                aaw.resolve_bucket_owner(make_config(bad), make_sts())


class MainTest(unittest.TestCase):
    def run_main(self, owner="", put_object_error=None):
        events = [{"event_id": f"e{i}", "timestamp": "2020-01-01T00:00:00Z"} for i in range(3)]
        table = mock.MagicMock()
        table.scan.return_value = {"Items": events}
        writer = table.batch_writer.return_value.__enter__.return_value
        dynamodb = mock.Mock()
        dynamodb.Table.return_value = table
        s3 = mock.Mock()
        if put_object_error:
            s3.put_object.side_effect = put_object_error
        sts = make_sts()

        def client(name, **_):
            return {"s3": s3, "sts": sts}[name]

        def read(self, *_args, **_kwargs):
            self.read_string(CONFIG % owner)

        with mock.patch.object(configparser.ConfigParser, "read", read), \
                mock.patch.object(aaw.boto3, "client", side_effect=client), \
                mock.patch.object(aaw.boto3, "resource", return_value=dynamodb), \
                mock.patch("builtins.print"):
            try:
                aaw.main()
            except Exception as exc:  # noqa: BLE001 - surfaced to the test
                return s3, table, writer, exc
        return s3, table, writer, None

    def test_every_put_object_carries_expected_bucket_owner(self):
        s3, _, writer, err = self.run_main()
        self.assertIsNone(err)
        self.assertEqual(s3.put_object.call_count, 2)
        for call in s3.put_object.call_args_list:
            self.assertEqual(call.kwargs["Bucket"], "otterworks-audit-archive")
            self.assertEqual(call.kwargs["ExpectedBucketOwner"], CALLER_ACCOUNT)
        self.assertEqual(writer.delete_item.call_count, 3)

    def test_rejected_archive_upload_keeps_dynamodb_events(self):
        s3, _, writer, err = self.run_main(owner="111122223333", put_object_error=RuntimeError("AccessDenied"))
        self.assertIsInstance(err, RuntimeError)
        s3.put_object.assert_called_once()
        self.assertEqual(s3.put_object.call_args.kwargs["ExpectedBucketOwner"], "111122223333")
        writer.delete_item.assert_not_called()

    def test_invalid_owner_aborts_before_scan_or_upload(self):
        s3, table, _, err = self.run_main(owner="abc")
        self.assertIsInstance(err, ValueError)
        table.scan.assert_not_called()
        s3.put_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
