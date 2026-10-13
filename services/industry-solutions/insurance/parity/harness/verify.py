"""Offline transcript check: one fresh transcript per scenario, none orphaned."""

from __future__ import annotations

import json
import sys

from harness.common import TRANSCRIPTS, load_scenarios, stale_reasons, transcript_path


def main() -> int:
    errors = []
    scenarios = load_scenarios()
    expected = {transcript_path(s) for s in scenarios}
    for scenario in scenarios:
        path = transcript_path(scenario)
        if not path.exists():
            errors.append(f"missing transcript {path.name}")
            continue
        transcript = json.loads(path.read_text())
        errors += [f"{path.name}: {reason}" for reason in stale_reasons(scenario, transcript)]
    for path in sorted(set(TRANSCRIPTS.rglob("*.json")) - expected):
        errors.append(f"orphan transcript {path.relative_to(TRANSCRIPTS)}")
    for error in errors:
        print(f"FAIL {error}")
    print(f"transcripts={len(expected)} errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
