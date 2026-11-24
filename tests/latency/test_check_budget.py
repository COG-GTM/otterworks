import json
import tempfile
import unittest
from pathlib import Path

import check_budget


def result(**p95s):
    return {"endpoints": {n: {"p50": 1, "p95": v, "p99": v, "count": 100} for n, v in p95s.items()}}


class EvaluateTest(unittest.TestCase):
    def test_within_budget_passes(self):
        rows, failed = check_budget.evaluate([result(a=40, b=90)], 100, {})
        self.assertFalse(failed)
        self.assertEqual([r[3] for r in rows], ["OK", "OK"])

    def test_over_budget_fails(self):
        _, failed = check_budget.evaluate([result(a=40, b=150)], 100, {})
        self.assertTrue(failed)

    def test_per_endpoint_budget_overrides_default(self):
        _, failed = check_budget.evaluate([result(login=180)], 100, {"login": {"p95_ms": 200}})
        self.assertFalse(failed)

    def test_waiver_reports_but_does_not_fail(self):
        rows, failed = check_budget.evaluate(
            [result(slow=900)], 100, {"slow": {"p95_ms": 100, "waiver": "approved exception"}})
        self.assertFalse(failed)
        self.assertEqual(rows[0][3], "WAIVED")

    def test_excluded_endpoint_is_skipped(self):
        rows, failed = check_budget.evaluate([result(a=40, slow=900)], 100, {}, {"slow"})
        self.assertFalse(failed)
        self.assertEqual([r[0] for r in rows], ["a"])

    def test_missing_budget_fails(self):
        _, failed = check_budget.evaluate([result(a=1)], None, {})
        self.assertTrue(failed)

    def test_main_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            budgets = Path(d, "b.json")
            budgets.write_text(json.dumps({"default_p95_ms": 100}))
            res = Path(d, "r.json")
            res.write_text(json.dumps(result(a=50)))
            self.assertEqual(check_budget.main(["--budgets", str(budgets), str(res)]), 0)
            res.write_text(json.dumps(result(a=150)))
            self.assertEqual(check_budget.main(["--budgets", str(budgets), str(res)]), 1)


if __name__ == "__main__":
    unittest.main()
