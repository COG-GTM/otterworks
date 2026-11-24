#!/usr/bin/env python3
"""Fail when any endpoint's measured p95 is over its budget.

Usage: python3 tests/latency/check_budget.py [--budgets FILE] [--exclude ENDPOINT] RESULT.json [RESULT.json ...]

RESULT files are written by the k6 scripts in this folder. Budgets live in
budgets.json: {"default_p95_ms": N, "max_error_rate": R, "endpoints": {name: {"p95_ms": N, "waiver": "why"}}}.
p95 covers successful responses only; an endpoint with no successful sample
(NO DATA) or an error rate above max_error_rate (ERRORS, default 0.01) fails.
An endpoint with a "waiver" is reported but does not fail the check; a waiver
is an approved release exception and should name who signed it off.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_MAX_ERROR_RATE = 0.01


def load_budgets(path):
    data = json.loads(Path(path).read_text())
    return data.get("default_p95_ms"), data.get("endpoints", {}), data.get("max_error_rate", DEFAULT_MAX_ERROR_RATE)


def evaluate(results, default_p95, budgets, exclude=(), max_error_rate=DEFAULT_MAX_ERROR_RATE):
    """Returns (rows, failed). rows: (endpoint, p95, budget, status)."""
    rows, failed = [], False
    for result in results:
        for name, stats in result["endpoints"].items():
            if name in exclude:
                continue
            entry = budgets.get(name, {})
            budget = entry.get("p95_ms", default_p95)
            p95 = stats.get("p95")
            if budget is None:
                status = "NO BUDGET"
                failed = True
            elif not stats.get("count") or p95 is None:
                status = "NO DATA"
                failed = True
            elif (stats.get("error_rate") or 0) > max_error_rate:
                status = "ERRORS"
                failed = True
            elif p95 <= budget:
                status = "OK"
            elif entry.get("waiver"):
                status = "WAIVED"
            else:
                status = "OVER"
                failed = True
            rows.append((name, p95, budget, status))
    rows.sort(key=lambda r: float("-inf") if r[1] is None else -r[1])
    return rows, failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budgets", default=str(HERE / "budgets.json"))
    parser.add_argument("--exclude", action="append", default=[], metavar="ENDPOINT",
                        help="leave an endpoint out of the check (repeatable)")
    parser.add_argument("results", nargs="+")
    args = parser.parse_args(argv)

    default_p95, budgets, max_error_rate = load_budgets(args.budgets)
    results = [json.loads(Path(p).read_text()) for p in args.results]
    rows, failed = evaluate(results, default_p95, budgets, set(args.exclude), max_error_rate)

    print(f"{'endpoint':34} {'p95 ms':>8} {'budget':>8}  status")
    for name, p95, budget, status in rows:
        print(f"{name:34} {p95 if p95 is not None else '-':>8} {budget if budget is not None else '-':>8}  {status}")
    print("\nFAIL: an endpoint is over budget, erroring or unmeasured" if failed else "\nPASS: every endpoint within its p95 budget")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
