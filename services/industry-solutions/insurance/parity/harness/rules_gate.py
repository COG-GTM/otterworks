"""Rules gate: every scenario is claimed, every rule has a decision, a real legacy
source range and a target unit test, and every divergence names a ledger rule."""

from __future__ import annotations

import re
import sys

import yaml

from harness.common import ROOT, RULES, SERVICE_TESTS, SOURCE_FILES, load_scenarios

ALLOWED_SOURCES = {str(path.relative_to(ROOT)): path for path in SOURCE_FILES}
REQUIRED = ("id", "statement", "source", "scenarios", "decision")


def main() -> int:
    errors: list[str] = []
    markers = {
        rule_id
        for path in SERVICE_TESTS.rglob("*.py")
        for rule_id in re.findall(r'pytest\.mark\.rule\(["\']([^"\']+)["\']\)', path.read_text())
    }
    rules: dict[str, dict] = {}
    for ledger_path in sorted(RULES.glob("*.rules.yaml")):
        ledger = yaml.safe_load(ledger_path.read_text())
        module = ledger.get("module")
        if f"{module}.rules.yaml" != ledger_path.name:
            errors.append(f"{ledger_path.name}: module must match file name")
        for rule in ledger.get("rules", []):
            missing = [field for field in REQUIRED if not rule.get(field)]
            if missing:
                errors.append(f"{ledger_path.name}: rule {rule.get('id')} missing {missing}")
                continue
            if rule["id"] in rules:
                errors.append(f"{rule['id']}: duplicate rule id")
            rules[rule["id"]] = {**rule, "module": module}
    claimed: dict[str, set[str]] = {}
    for rule_id, rule in rules.items():
        decision = rule["decision"]
        if decision.get("status") in (None, "pending") or not decision.get("reviewer") or not decision.get("date"):
            errors.append(f"{rule_id}: decision needs a non-pending status, reviewer and date")
        source = rule["source"]
        path = ALLOWED_SOURCES.get(source.get("file", ""))
        lines = source.get("lines") or []
        if path is None:
            errors.append(f"{rule_id}: source must be one of {sorted(ALLOWED_SOURCES)}")
        elif len(lines) != 2 or not 1 <= lines[0] <= lines[1] <= len(path.read_text().splitlines()):
            errors.append(f"{rule_id}: invalid source line range {lines}")
        if rule_id not in markers:
            errors.append(f"{rule_id}: no target unit test marked @pytest.mark.rule('{rule_id}')")
        for scenario_id in rule["scenarios"]:
            claimed.setdefault(scenario_id, set()).add(rule_id)
    for marker in sorted(markers - rules.keys()):
        errors.append(f"{marker}: test marker has no ledger rule")
    scenarios = {scenario["id"]: scenario for scenario in load_scenarios()}
    for scenario_id, scenario in scenarios.items():
        owners = claimed.get(scenario_id, set())
        if not owners:
            errors.append(f"{scenario_id}: not claimed by any rule")
        if any(rules[owner]["module"] != scenario["module"] for owner in owners):
            errors.append(f"{scenario_id}: claimed by a rule from another module")
        divergence = scenario.get("divergence")
        if divergence:
            rule = rules.get(divergence.get("rule", ""))
            if rule is None or scenario_id not in rule["scenarios"]:
                errors.append(f"{scenario_id}: divergence must name a ledger rule that claims it")
            elif rule["decision"]["status"] != "divergence-accepted":
                errors.append(f"{scenario_id}: divergence rule {rule['id']} is not divergence-accepted")
            if not divergence.get("reason"):
                errors.append(f"{scenario_id}: divergence needs a reason")
    for scenario_id in sorted(claimed.keys() - scenarios.keys()):
        errors.append(f"{scenario_id}: claimed but no scenario file exists")
    for error in errors:
        print(f"FAIL {error}")
    print(f"rules={len(rules)} scenarios={len(scenarios)} markers={len(markers)} errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
