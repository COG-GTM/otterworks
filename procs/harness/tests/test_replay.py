from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from procs.harness.replay import (
    classify_transcript,
    compare,
    normalize,
    source_matches,
    write_report,
)


def test_pending_module_is_skip() -> None:
    transcript = {"module": "rating", "scenario": "RATING-001"}
    routes = {"rating": {"status": "pending"}}
    assert classify_transcript(transcript, routes) == "SKIP"


def test_source_sha_mismatch_is_detected(monkeypatch) -> None:
    monkeypatch.setattr("procs.harness.replay.source_sha", lambda: "actual")
    assert not source_matches("recorded")


def test_business_field_mismatch_is_diagnostic() -> None:
    transcript = {"scenario": "PLANS-001", "business_fields": {"code": "STARTER"}, "probes": {}}
    contract = {"response": {"business_fields": {"code": {"json_path": "$.code"}}, "probes": {}}}
    failures, errors = compare(transcript, contract, {"code": "GROWTH"})
    assert not errors
    assert failures == [{"kind": "field", "name": "code", "expected": "STARTER", "actual": "GROWTH"}]


def test_probe_mismatch_is_diagnostic() -> None:
    transcript = {"scenario": "PLANS-004", "business_fields": {}, "probes": {"rows": [{"id": 1}]}}
    contract = {"response": {"business_fields": {}, "probes": {"rows": {"json_path": "$.rows"}}}}
    failures, errors = compare(transcript, contract, {"rows": [{"id": 2}]})
    assert not errors
    assert failures[0]["kind"] == "probe"


def test_unmapped_business_field_and_probe_are_contract_errors() -> None:
    transcript = {
        "scenario": "PLANS-001",
        "business_fields": {"unmapped": "value"},
        "probes": {"missing_probe": "value"},
    }
    failures, errors = compare(transcript, {"response": {"business_fields": {}, "probes": {}}}, {})
    assert not failures
    assert "business field unmapped" in errors[0]
    assert "probe missing_probe" in errors[1]


def test_structured_rows_are_sorted_and_normalized() -> None:
    contract = {
        "response": {
            "business_fields": {
                "rows": {"json_path": "$.rows", "type": "rows", "sort_by": ["id"]}
            },
            "probes": {},
        }
    }
    transcript = {"scenario": "x", "business_fields": {"rows": [{"id": "1"}]}, "probes": {}}
    failures, errors = compare(transcript, contract, {"rows": [{"id": "1"}]})
    assert not failures
    assert not errors
    assert normalize({"b": 2, "a": 1}) == {"a": 1, "b": 2}


def test_contract_errors_are_written_to_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("procs.harness.replay.REPORT_DIR", tmp_path)
    write_report("sha", [], ["PLANS-001: business field missing"])
    assert "Contract error" in (tmp_path / "parity.md").read_text()
