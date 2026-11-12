"""Static guard: every S3 request in etl/scripts must pin the bucket owner."""

import ast
import pathlib
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def _calls(path):
    return [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Call)]


def _kwargs(call):
    return {k.arg for k in call.keywords if k.arg}


class BucketOwnerCoverageTest(unittest.TestCase):
    def test_every_bucket_call_passes_expected_bucket_owner(self):
        checked = 0
        for path in sorted(SCRIPTS.glob("*.py")):
            for call in _calls(path):
                kwargs = _kwargs(call)
                if "Bucket" not in kwargs:
                    continue
                checked += 1
                where = "%s:%d" % (path.name, call.lineno)
                self.assertIn("ExpectedBucketOwner", kwargs, where)
                if "CopySource" in kwargs:
                    self.assertIn("ExpectedSourceBucketOwner", kwargs, where)
        self.assertGreaterEqual(checked, 14)

    def test_analytics_deletes_sqs_events_only_after_data_lake_upload(self):
        calls = [
            c for c in _calls(SCRIPTS / "analytics_daily.py")
            if isinstance(c.func, ast.Attribute)
        ]
        lake_puts = [
            c.lineno for c in calls
            if c.func.attr == "put_object"
            and isinstance(c.func.value, ast.Name) and c.func.value.id == "s3_client"
        ]
        deletes = [c.lineno for c in calls if c.func.attr == "delete_message_batch"]
        self.assertTrue(lake_puts and deletes)
        self.assertGreater(min(deletes), max(lake_puts))


if __name__ == "__main__":
    unittest.main()
