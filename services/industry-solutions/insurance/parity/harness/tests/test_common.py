from __future__ import annotations

from decimal import Decimal

import pytest

from harness.common import comparable_outcome, normalize, normalize_row
from harness.record import seed_statements


@pytest.mark.parametrize(
    ("value", "kind", "expected"),
    [
        (Decimal("38.00"), "decimal", "38"),
        ("38", "decimal", "38"),
        (Decimal("0.00"), "decimal", "0"),
        (Decimal(100), "decimal", "100"),
        ("12.35", "decimal", "12.35"),
        (Decimal(7), "integer", 7),
        ("CHAR  ", "text", "CHAR"),
        (None, "decimal", None),
    ],
)
def test_normalize(value: object, kind: str, expected: object) -> None:
    assert normalize(value, kind) == expected


def test_rows_match_oracle_upper_case_columns() -> None:
    assert normalize_row({"AGENT_ID": 1, "SPLIT_PCT": Decimal("50.00")},
                         {"agent_id": "integer", "split_pct": "decimal"}) == {"agent_id": 1, "split_pct": "50"}


def test_only_application_error_messages_are_graded() -> None:
    oracle_internal = {"status": "error", "ora_code": -1, "message": "ORA text (SCHEMA.IDX)"}
    assert comparable_outcome(oracle_internal) == {"status": "error", "ora_code": -1}
    business = {"status": "error", "ora_code": -20006, "message": "Duplicate agent"}
    assert comparable_outcome(business) == business


def test_seed_parser_reads_frozen_fixture() -> None:
    statements = seed_statements()
    assert not any(s.upper().startswith(("WHENEVER", "EXIT", "COMMIT")) for s in statements)
    assert sum(s.upper().startswith("INSERT INTO AGENTS") for s in statements) == 4
