from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.domain import rates
from app.domain.calculation import calculate_policy_commission, period_as_of
from app.domain.errors import (
    BadSplitError,
    InvalidPeriodError,
    NoRateError,
    PolicyNotActiveError,
    UnknownPolicyError,
)
from app.domain.model import Split
from app.domain.oracle_compat import monthly_commission
from tests.fakes import FakeRepository, transactional


@pytest.mark.rule("INS-CALC-001")
def test_unknown_policy_rejected(repo: FakeRepository) -> None:
    with pytest.raises(UnknownPolicyError, match="Unknown policy: 42"):
        calculate_policy_commission(repo, 42, "2025-06", "t")


@pytest.mark.rule("INS-CALC-002")
def test_lapsed_policy_rejected(repo: FakeRepository) -> None:
    with pytest.raises(PolicyNotActiveError, match="Policy 5 is LAPSED") as err:
        calculate_policy_commission(repo, 5, "2025-06", "t")
    assert err.value.ora_code == -20008


@pytest.mark.rule("INS-CALC-002")
def test_status_checked_before_period(repo: FakeRepository) -> None:
    with pytest.raises(PolicyNotActiveError):
        calculate_policy_commission(repo, 5, "garbage", "t")


@pytest.mark.rule("INS-CALC-003")
def test_three_way_split_amounts(repo: FakeRepository) -> None:
    rows = calculate_policy_commission(repo, 4, "2025-06", "t")
    assert [(r.agent_id, r.rate_id, r.commission_amt) for r in rows] == [
        (1, 4, D("38.00")),
        (2, 1, D("19.20")),
        (3, 1, D("12.80")),
    ]
    assert all(r.base_premium == D("9600.00") for r in rows)


@pytest.mark.rule("INS-CALC-003")
@pytest.mark.parametrize(
    ("premium", "rate", "split", "expected"),
    [
        (D("1800.00"), D("9.50"), D("100.00"), D("14.25")),
        (D("1000.00"), D("10.00"), D("33.33"), D("2.78")),
        (D("1234.56"), D("7.77"), D("12.34"), D("0.99")),
        (D("100.00"), D("0.30"), D("50.00"), D("0.01")),
    ],
)
def test_formula_rounds_half_up_per_row(premium: D, rate: D, split: D, expected: D) -> None:
    assert monthly_commission(premium, rate, split) == expected


@pytest.mark.rule("INS-CALC-004")
def test_rate_resolved_as_of_last_day_of_period(repo: FakeRepository) -> None:
    rates.upsert_commission_rate(repo, "AUTO-STD", None, D("9"), date(2025, 7, 31), "t")
    june = calculate_policy_commission(repo, 4, "2025-06", "t")
    july = calculate_policy_commission(repo, 4, "2025-07", "t")
    assert june[1].rate_id == 1
    assert july[1].rate_id == 5
    assert period_as_of("2024-02") == date(2024, 2, 29)


@pytest.mark.rule("INS-CALC-005")
def test_recalculation_replaces_rows(repo: FakeRepository) -> None:
    calculate_policy_commission(repo, 4, "2025-06", "t")
    repo.replace_splits(4, [Split(1, D("100.00"))])
    calculate_policy_commission(repo, 4, "2025-06", "t")
    assert [k for k in repo.state["ledger"]] == [(4, 1, "2025-06")]


@pytest.mark.rule("INS-CALC-006")
def test_policy_without_splits_rejected(repo: FakeRepository) -> None:
    with pytest.raises(BadSplitError, match="Policy 3 has no split allocation"):
        transactional(repo, lambda: calculate_policy_commission(repo, 3, "2025-06", "t"))
    assert repo.state["audit"] == []


@pytest.mark.rule("INS-CALC-007")
def test_missing_rate_rolls_back_whole_calculation(repo: FakeRepository) -> None:
    with pytest.raises(NoRateError, match="AUTO-STD/agent 1 on 2023-06-30"):
        transactional(repo, lambda: calculate_policy_commission(repo, 4, "2023-06", "t"))
    assert repo.state["ledger"] == {}


@pytest.mark.rule("INS-CALC-008")
def test_calculation_audited(repo: FakeRepository) -> None:
    calculate_policy_commission(repo, 2, "2025-06", "calc")
    assert repo.state["audit"] == [
        ("COMMISSION_CALC", "HOME-PLUS", None, 2, "2025-06 rows=2", "calc")
    ]


@pytest.mark.rule("INS-CALC-009")
@pytest.mark.parametrize(
    ("period", "ora_code"),
    [
        ("2025-13", -1843),
        ("2025-00", -1843),
        ("2025-6", -1861),
        ("June", -1861),
        ("", -1861),
        ("0000-01", -1841),
        ("\uff12\uff10\uff12\uff15-06", -1861),
        ("2025-06\n", -1861),
    ],
)
def test_period_must_be_canonical(repo: FakeRepository, period: str, ora_code: int) -> None:
    with pytest.raises(InvalidPeriodError) as err:
        calculate_policy_commission(repo, 1, period, "t")
    assert err.value.ora_code == ora_code
