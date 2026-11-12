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

    def test_analytics_releases_sqs_events_when_data_lake_upload_fails(self):
        tree = ast.parse((SCRIPTS / "analytics_daily.py").read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body_attrs = {
                c.func.attr for stmt in node.body for c in ast.walk(stmt)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            }
            handler_attrs = {
                c.func.attr for h in node.handlers for c in ast.walk(h)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            }
            if "put_object" in body_attrs and "change_message_visibility_batch" in handler_attrs:
                return
        self.fail("data lake put_object calls must release SQS visibility on failure")


if __name__ == "__main__":
    unittest.main()
