"""Offline transcript check: one transcript per scenario, none orphaned, none stale."""

from __future__ import annotations

import json
import sys

from harness.common import (
    TRANSCRIPTS,
    fixture_sha,
    load_scenarios,
    source_sha,
    transcript_path,
)


def main() -> int:
    errors = []
    expected = {transcript_path(s) for s in load_scenarios()}
    for path in sorted(expected):
        if not path.exists():
            errors.append(f"missing transcript {path.name}")
            continue
        transcript = json.loads(path.read_text())
        if transcript.get("source_sha") != source_sha():
            errors.append(f"{path.name}: PL/SQL source changed since recording")
        if transcript.get("fixture_sha") != fixture_sha():
            errors.append(f"{path.name}: fixture schema/seed changed since recording")
    for path in sorted(set(TRANSCRIPTS.rglob("*.json")) - expected):
        errors.append(f"orphan transcript {path.relative_to(TRANSCRIPTS)}")
    for error in errors:
        print(f"FAIL {error}")
    print(f"transcripts={len(expected)} errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
