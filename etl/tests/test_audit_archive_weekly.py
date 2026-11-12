import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from botocore.exceptions import ClientError

SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "audit_archive_weekly.py"
)
spec = importlib.util.spec_from_file_location("audit_archive_weekly", SCRIPT)
audit_archive_weekly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_archive_weekly)

REPORT_PREFIX = "reports/compliance/audit-archive/"
THROTTLED = ClientError(
    {
        "Error": {
            "Code": "ProvisionedThroughputExceededException",
            "Message": "throttled",
        }
    },
    "BatchWriteItem",
)


class FakeBatchWriter:
    def __init__(self, error):
        self.error = error

    def __enter__(self):
        if self.error is not None:
            raise self.error
        return self

    def __exit__(self, *exc):
        return False

    def delete_item(self, Key):
        pass


class FakeTable:
    def __init__(self, event_count, errors):
        self.event_count = event_count
        self.errors = list(errors)

    def scan(self, **kwargs):
        return {
            "Items": [
                {"event_id": "e%d" % i, "timestamp": "2020-01-01T00:00:00Z"}
                for i in range(self.event_count)
            ]
        }

    def batch_writer(self):
        return FakeBatchWriter(self.errors.pop(0) if self.errors else None)


class BatchDeleteErrorHandlingTest(unittest.TestCase):
    def run_main(self, event_count, errors):
        resource = mock.MagicMock()
        resource.Table.return_value = FakeTable(event_count, errors)
        s3 = mock.MagicMock()
        stdout = io.StringIO()
        with (
            mock.patch.object(
                audit_archive_weekly.boto3, "resource", return_value=resource
            ),
            mock.patch.object(audit_archive_weekly.boto3, "client", return_value=s3),
            mock.patch.object(
                audit_archive_weekly.configparser.ConfigParser,
                "get",
                lambda self, section, key, **kw: "x",
            ),
            redirect_stdout(stdout),
        ):
            try:
                audit_archive_weekly.main()
            finally:
                self.output = stdout.getvalue()
                self.uploaded_keys = [
                    c.kwargs["Key"] for c in s3.put_object.call_args_list
                ]

    def report_uploaded(self):
        return any(k.startswith(REPORT_PREFIX) for k in self.uploaded_keys)

    def test_aws_error_on_full_batch_is_logged_and_run_continues(self):
        self.run_main(30, [THROTTLED, None])
        self.assertIn("WARNING: failed to delete batch of 25 events", self.output)
        self.assertIn("Deleted 5 events from DynamoDB", self.output)
        self.assertTrue(self.report_uploaded())

    def test_aws_error_on_trailing_batch_is_logged_and_run_continues(self):
        self.run_main(30, [None, THROTTLED])
        self.assertIn("WARNING: failed to delete batch of 5 events", self.output)
        self.assertIn("Deleted 25 events from DynamoDB", self.output)
        self.assertTrue(self.report_uploaded())

    def test_fatal_errors_escape_and_skip_compliance_report(self):
        for position in (0, 1):
            for error in (KeyboardInterrupt(), SystemExit(143), KeyError("event_id")):
                with self.subTest(batch=position, error=type(error).__name__):
                    errors = [None, None]
                    errors[position] = error
                    with self.assertRaises(type(error)):
                        self.run_main(30, errors)
                    self.assertNotIn("WARNING", self.output)
                    self.assertFalse(self.report_uploaded())


if __name__ == "__main__":
    unittest.main()
