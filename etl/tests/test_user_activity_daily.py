"""Run with: python3 -m unittest discover -s etl/tests"""

import configparser
import importlib.util
import pathlib
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest import mock

from botocore.exceptions import ClientError

try:
    import psycopg2  # noqa: F401
except ImportError:
    sys.modules["psycopg2"] = types.ModuleType("psycopg2")

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "user_activity_daily.py"
_spec = importlib.util.spec_from_file_location("user_activity_daily", SCRIPT)
uad = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uad)

OWNER = "111122223333"
BASE_INI = """
[aws]
access_key = AKIAEXAMPLE
secret_key = example
region = us-east-1
{account}
[database]
host = db
port = 5432
database = d
user = u
password = p

[s3]
data_lake_bucket = otterworks-data-lake
"""


def _client_error(code, status):
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "GetObject")


class UserActivityBucketOwnerTest(unittest.TestCase):
    def run_main(self, account_line=f"account_id = {OWNER}", get_error=None):
        ini = BASE_INI.format(account=account_line)
        conn = mock.MagicMock()
        conn.cursor.return_value.fetchall.return_value = [
            (datetime.now(timezone.utc).date(), 3, 1, 1, 10, 1, 1, 1, 1, 1, 1, 100)
        ]
        s3 = mock.MagicMock()
        s3.get_object.side_effect = get_error or _client_error("NoSuchKey", 404)
        with mock.patch.object(configparser.ConfigParser, "read", lambda self, f, encoding=None: self.read_string(ini)), \
                mock.patch.object(uad.psycopg2, "connect", create=True, return_value=conn) as connect, \
                mock.patch.object(uad.boto3, "client", return_value=s3) as client:
            uad.main()
        return s3, connect, client

    def test_every_s3_call_sends_expected_bucket_owner(self):
        s3, _, _ = self.run_main()
        self.assertEqual(s3.get_object.call_count, 30)
        self.assertEqual(s3.put_object.call_count, 2)
        for call in s3.get_object.call_args_list + s3.put_object.call_args_list:
            self.assertEqual(call.kwargs["ExpectedBucketOwner"], OWNER)
            self.assertEqual(call.kwargs["Bucket"], "otterworks-data-lake")

    def test_missing_account_id_fails_before_any_io(self):
        for line in ("", "account_id =", "account_id = 1234", "account_id = abcdefghijkl"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.run_main(account_line=line)

    def test_missing_account_id_makes_no_db_or_s3_calls(self):
        with mock.patch.object(uad.psycopg2, "connect", create=True) as connect, \
                mock.patch.object(uad.boto3, "client") as client, \
                mock.patch.object(configparser.ConfigParser, "read",
                                  lambda self, f, encoding=None: self.read_string(BASE_INI.format(account=""))), \
                self.assertRaises(ValueError):
            uad.main()
        connect.assert_not_called()
        client.assert_not_called()

    def test_access_denied_on_missing_day_is_skipped(self):
        # Without s3:ListBucket a missing key returns 403 AccessDenied.
        s3, _, _ = self.run_main(get_error=_client_error("AccessDenied", 403))
        self.assertEqual(s3.put_object.call_count, 2)


if __name__ == "__main__":
    unittest.main()
