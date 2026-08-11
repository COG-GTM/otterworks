from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from procs.harness.record import normalized
from procs.harness.record import write_transcripts
from procs.harness.replay import normalize


def test_partial_record_preserves_other_index_entries(tmp_path) -> None:
    (tmp_path / "index.json").write_text(
        json.dumps(
            [
                {"module": "plans", "scenario": "PLANS-001", "rules": ["PLANS-001"]},
                {"module": "rating", "scenario": "RATING-001", "rules": ["RATING-001"]},
            ]
        )
    )
    write_transcripts(
        [
            {
                "module": "plans",
                "scenario": "PLANS-001",
                "rules": ["PLANS-001"],
                "business_fields": {},
                "probes": {},
            }
        ],
        "current",
        tmp_path,
    )
    index = json.loads((tmp_path / "index.json").read_text())
    assert {(item["module"], item["scenario"]) for item in index} == {
        ("plans", "PLANS-001"),
        ("rating", "RATING-001"),
    }


def test_typed_capture_round_trips_with_replay_normalization() -> None:
    assert normalized("1", "integer") == normalize("1", "integer") == 1
    assert (
        normalized("2026-02-28", "date")
        == normalize("2026-02-28", "date")
        == "2026-02-28"
    )
