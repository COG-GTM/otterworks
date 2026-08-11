from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "procs" / "scenarios"
STATUS = {"plans": "extracted", "rating": "pending", "invoicing": "pending", "dunning": "pending"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module")
    args = parser.parse_args()
    modules = [args.module] if args.module else sorted(STATUS)
    for module in modules:
        paths = sorted((SCENARIOS / module).glob("*.yaml"))
        if not paths:
            parser.error(f"unknown module: {module}")
        scenarios = [yaml.safe_load(path.read_text()) for path in paths]
        rules = sorted({rule for scenario in scenarios for rule in scenario.get("rules", [])})
        print(
            f"{module:12} {STATUS.get(module, 'pending'):9} "
            f"scenarios={len(scenarios):2} rule_claims={len(rules):2}"
        )
        for scenario in scenarios:
            print(f"  {scenario['id']}: {', '.join(scenario.get('rules', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
