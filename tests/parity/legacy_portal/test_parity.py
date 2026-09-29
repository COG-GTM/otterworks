import difflib
import json
from pathlib import Path

import httpx
import pytest

from harness import Scenario, dump, run_scenario
from scenarios import SCENARIOS

pytestmark = pytest.mark.parity


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_scenario_matches_golden(
    scenario: Scenario,
    clients: dict[str, httpx.Client],
    record_golden: bool,
    golden_dir: Path,
) -> None:
    transcript = run_scenario(scenario, clients.__getitem__)
    golden_path = golden_dir / f"{scenario.name}.json"

    if record_golden:
        golden_dir.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(dump(transcript), encoding="utf-8")
        return

    assert golden_path.exists(), (
        f"no golden transcript {golden_path.name}; record it with make parity-legacy-portal-record"
    )
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    if transcript != expected:
        diff = "".join(
            difflib.unified_diff(
                dump(expected).splitlines(keepends=True),
                dump(transcript).splitlines(keepends=True),
                fromfile=f"golden/{golden_path.name}",
                tofile="actual",
            )
        )
        pytest.fail(f"transcript differs from golden:\n{diff}", pytrace=False)


def test_every_golden_transcript_has_a_scenario(
    golden_dir: Path, record_golden: bool
) -> None:
    names = {s.name for s in SCENARIOS}
    assert len(names) == len(SCENARIOS), "duplicate scenario names"
    if record_golden:
        return
    orphans = sorted(p.stem for p in golden_dir.glob("*.json") if p.stem not in names)
    assert not orphans, f"golden transcripts without a scenario: {orphans}"
