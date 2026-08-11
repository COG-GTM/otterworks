from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "procs" / "scenarios"
RULES = ROOT / "procs" / "rules"
TESTS = ROOT / "services" / "billing-service" / "tests"


def fail(messages: list[str]) -> int:
    for message in messages:
        print(f"ERROR: {message}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True)
    args = parser.parse_args()
    ledger_path = RULES / f"{args.module}.rules.yaml"
    if not ledger_path.exists():
        return fail([f"no ledger for module {args.module}"])
    ledger = yaml.safe_load(ledger_path.read_text())
    errors: list[str] = []
    scenarios = [yaml.safe_load(path.read_text()) for path in sorted((SCENARIOS / args.module).glob("*.yaml"))]
    scenario_ids = {scenario["id"] for scenario in scenarios}
    rules = ledger.get("rules", [])
    claimed = {scenario_id for rule in rules for scenario_id in rule.get("scenarios", [])}
    markers = {
        rule_id
        for path in TESTS.rglob("*.py")
        for rule_id in re.findall(r'pytest\.mark\.rule\(["\']([^"\']+)["\']\)', path.read_text())
    }
    proc_dir = ROOT / "services" / "legacy-billing" / "db" / "procs"
    for rule in rules:
        rule_id = rule.get("id")
        decision = rule.get("decision", {})
        if decision.get("status") in {None, "pending"}:
            errors.append(f"{rule_id}: decision is pending")
        if not decision.get("reviewer"):
            errors.append(f"{rule_id}: reviewer is required")
        if not decision.get("date"):
            errors.append(f"{rule_id}: date is required")
        question = rule.get("question")
        if question and not rule.get("answer") and not decision.get("note"):
            errors.append(f"{rule_id}: question has no answer")
        for scenario_id in rule.get("scenarios", []):
            if scenario_id not in scenario_ids:
                errors.append(f"{rule_id}: unknown scenario {scenario_id}")
        source = rule.get("source", {})
        source_path = ROOT / source.get("file", "")
        lines = source.get("lines", [])
        if not source_path.exists() or len(lines) != 2:
            errors.append(f"{rule_id}: source does not resolve")
        else:
            line_count = len(source_path.read_text().splitlines())
            if lines[0] < 1 or lines[1] > line_count or lines[0] > lines[1]:
                errors.append(f"{rule_id}: source line range is invalid")
            if source_path.parent != proc_dir:
                errors.append(f"{rule_id}: source is outside the module proc directory")
        if rule_id not in markers:
            errors.append(f"{rule_id}: no target test marker")
    for scenario_id in sorted(scenario_ids - claimed):
        errors.append(f"{scenario_id}: not claimed by a rule")
    if errors:
        return fail(errors)
    print(f"Rules gate PASS: {args.module} rules={len(rules)} scenarios={len(scenario_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
