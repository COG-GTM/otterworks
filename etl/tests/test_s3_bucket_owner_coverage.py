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
        self.assertGreaterEqual(checked, 15)

    def test_analytics_checks_owner_before_consuming_sqs(self):
        calls = _calls(SCRIPTS / "analytics_daily.py")

        def first(attr):
            return min(
                c.lineno for c in calls
                if isinstance(c.func, ast.Attribute) and c.func.attr == attr
            )

        self.assertLess(first("head_bucket"), first("receive_message"))
        self.assertLess(first("head_bucket"), first("delete_message_batch"))


if __name__ == "__main__":
    unittest.main()
