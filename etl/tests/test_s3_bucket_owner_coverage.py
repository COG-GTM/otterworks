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

    def test_analytics_acks_sqs_only_through_load_then_ack(self):
        attrs = [
            c.func.attr for c in _calls(SCRIPTS / "analytics_daily.py")
            if isinstance(c.func, ast.Attribute)
        ]
        names = [
            c.func.id for c in _calls(SCRIPTS / "analytics_daily.py")
            if isinstance(c.func, ast.Name)
        ]
        self.assertIn("load_then_ack", names)
        self.assertNotIn("delete_message_batch", attrs)
        self.assertNotIn("change_message_visibility_batch", attrs)


if __name__ == "__main__":
    unittest.main()
