from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "procs" / "scenarios"
ROUTES = ROOT / "procs" / "routes.yaml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module")
    args = parser.parse_args()
    routes = yaml.safe_load(ROUTES.read_text()).get("modules", {})
    scenario_modules = {
        path.name for path in SCENARIOS.iterdir() if path.is_dir()
    }
    modules = [args.module] if args.module else sorted(set(routes) | scenario_modules)
    for module in modules:
        paths = sorted((SCENARIOS / module).glob("*.yaml"))
        if not paths:
            parser.error(f"unknown module: {module}")
        scenarios = [yaml.safe_load(path.read_text()) for path in paths]
        rules = sorted({rule for scenario in scenarios for rule in scenario.get("rules", [])})
        print(
            f"{module:12} {routes.get(module, {}).get('status', 'pending'):9} "
            f"scenarios={len(scenarios):2} rule_claims={len(rules):2}"
        )
        for scenario in scenarios:
            print(f"  {scenario['id']}: {', '.join(scenario.get('rules', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
