from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.domain import rates
from app.domain.errors import (
    ConstraintViolationError,
    DuplicateOpenRateError,
    InactiveAgentError,
    InvalidRateError,
    NoRateError,
    UnknownAgentError,
    UnknownProductError,
)
from tests.fakes import FakeRepository, transactional


@pytest.mark.rule("INS-RATE-001")
@pytest.mark.parametrize("pct", [D("0"), D("-1"), D("50.01"), D("75"), None])
def test_rate_outside_range_rejected(repo: FakeRepository, pct: D | None) -> None:
    with pytest.raises(InvalidRateError) as err:
        rates.upsert_commission_rate(repo, "AUTO-STD", None, pct, date(2025, 1, 1), "t")
    assert err.value.ora_code == -20001
    assert err.value.message.startswith("Rate must be in (0, 50]: ")


@pytest.mark.rule("INS-RATE-001")
def test_rate_message_uses_oracle_number_text(repo: FakeRepository) -> None:
    with pytest.raises(InvalidRateError, match=r"\(0, 50\]: 75$"):
        rates.upsert_commission_rate(repo, "AUTO-STD", None, D("75.00"), date(2025, 1, 1), "t")
    with pytest.raises(InvalidRateError, match=r"NULL$"):
        rates.upsert_commission_rate(repo, "AUTO-STD", None, None, date(2025, 1, 1), "t")


@pytest.mark.rule("INS-RATE-001")
def test_rate_upper_bound_inclusive(repo: FakeRepository) -> None:
    rate_id = rates.upsert_commission_rate(repo, "TERM-20", None, D("50"), date(2025, 1, 1), "t")
    assert repo.get_rate(rate_id).rate_pct == D("50.00")  # type: ignore[union-attr]


@pytest.mark.rule("INS-RATE-002")
def test_unknown_product_rejected(repo: FakeRepository) -> None:
    with pytest.raises(UnknownProductError, match="Unknown product: NOPE") as err:
        rates.upsert_commission_rate(repo, "NOPE", None, D("5"), date(2025, 1, 1), "t")
    assert err.value.ora_code == -20004


@pytest.mark.rule("INS-RATE-003")
def test_suspended_agent_rejected(repo: FakeRepository) -> None:
    with pytest.raises(InactiveAgentError, match="Agent 4 is SUSPENDED") as err:
        rates.upsert_commission_rate(repo, "AUTO-STD", 4, D("9"), date(2025, 1, 1), "t")
    assert err.value.ora_code == -20003


@pytest.mark.rule("INS-RATE-003")
def test_unknown_agent_rejected(repo: FakeRepository) -> None:
    with pytest.raises(UnknownAgentError, match="Unknown agent: 99") as err:
        rates.upsert_commission_rate(repo, "AUTO-STD", 99, D("9"), date(2025, 1, 1), "t")
    assert err.value.ora_code == -20002


@pytest.mark.rule("INS-RATE-003")
def test_product_checked_before_agent(repo: FakeRepository) -> None:
    with pytest.raises(UnknownProductError):
        rates.upsert_commission_rate(repo, "NOPE", 4, D("9"), date(2025, 1, 1), "t")


@pytest.mark.rule("INS-RATE-004")
def test_same_day_upsert_amends_in_place(repo: FakeRepository) -> None:
    first = rates.upsert_commission_rate(repo, "TERM-20", None, D("16"), date(2025, 7, 1), "a")
    second = rates.upsert_commission_rate(repo, "TERM-20", None, D("17"), date(2025, 7, 1), "b")
    assert first == second == 5
    amended = repo.get_rate(5)
    assert amended is not None
    assert (amended.rate_pct, amended.created_by) == (D("17.00"), "b")
    assert repo.get_rate(3).effective_to == date(2025, 6, 30)  # type: ignore[union-attr]


@pytest.mark.rule("INS-RATE-005")
def test_later_rate_closes_prior_open_rate_on_preceding_day(repo: FakeRepository) -> None:
    rate_id = rates.upsert_commission_rate(repo, "AUTO-STD", None, D("8.25"), date(2025, 7, 1), "t")
    assert rate_id == 5
    assert repo.get_rate(1).effective_to == date(2025, 6, 30)  # type: ignore[union-attr]
    assert repo.get_rate(4).effective_to is None  # agent override untouched  # type: ignore[union-attr]


@pytest.mark.rule("INS-RATE-006")
def test_rate_stored_at_cents_but_audited_raw(repo: FakeRepository) -> None:
    rate_id = rates.upsert_commission_rate(
        repo, "TERM-20", None, D("12.345"), date(2031, 1, 1), "probe"
    )
    assert repo.get_rate(rate_id).rate_pct == D("12.35")  # type: ignore[union-attr]
    assert repo.state["audit"][-1][4] == "rate_id=5 pct=12.345 from=2031-01-01"


@pytest.mark.rule("INS-RATE-006")
def test_rate_that_rounds_to_zero_violates_check(repo: FakeRepository) -> None:
    with pytest.raises(ConstraintViolationError) as err:
        rates.upsert_commission_rate(repo, "TERM-20", None, D("0.004"), date(2031, 1, 1), "t")
    assert err.value.ora_code == -2290


@pytest.mark.rule("INS-RATE-007")
def test_end_rate_closes_open_rate(repo: FakeRepository) -> None:
    rates.end_commission_rate(repo, "AUTO-STD", 1, date(2025, 12, 31), "t")
    assert repo.get_rate(4).effective_to == date(2025, 12, 31)  # type: ignore[union-attr]
    assert repo.state["audit"][-1] == ("RATE_END", "AUTO-STD", 1, None, "to=2025-12-31", "t")


@pytest.mark.rule("INS-RATE-007")
def test_end_rate_without_open_rate_rejected(repo: FakeRepository) -> None:
    with pytest.raises(NoRateError, match="No open rate for HOME-PLUS/2") as err:
        rates.end_commission_rate(repo, "HOME-PLUS", 2, date(2025, 12, 31), "t")
    assert err.value.ora_code == -20007
    with pytest.raises(NoRateError, match="No open rate for NOPE/default"):
        rates.end_commission_rate(repo, "NOPE", None, date(2025, 12, 31), "t")


@pytest.mark.rule("INS-RATE-007")
def test_end_rate_before_start_violates_date_check(repo: FakeRepository) -> None:
    with pytest.raises(ConstraintViolationError):
        rates.end_commission_rate(repo, "AUTO-STD", 1, date(2024, 5, 31), "t")


@pytest.mark.rule("INS-RATE-008")
def test_agent_specific_rate_beats_default(repo: FakeRepository) -> None:
    assert rates.resolve_rate(repo, "AUTO-STD", 1, date(2025, 6, 30)).rate_id == 4
    assert rates.resolve_rate(repo, "AUTO-STD", 2, date(2025, 6, 30)).rate_id == 1
    assert rates.resolve_rate(repo, "AUTO-STD", None, date(2025, 6, 30)).rate_id == 1


@pytest.mark.rule("INS-RATE-008")
def test_override_not_in_force_before_its_start(repo: FakeRepository) -> None:
    assert rates.resolve_rate(repo, "AUTO-STD", 1, date(2024, 5, 31)).rate_id == 1


@pytest.mark.rule("INS-RATE-008")
def test_latest_effective_rate_wins(repo: FakeRepository) -> None:
    rates.upsert_commission_rate(repo, "AUTO-STD", None, D("8.25"), date(2025, 7, 1), "t")
    assert rates.resolve_rate(repo, "AUTO-STD", 2, date(2025, 6, 30)).rate_id == 1
    assert rates.resolve_rate(repo, "AUTO-STD", 2, date(2025, 7, 31)).rate_id == 5


@pytest.mark.rule("INS-RATE-008")
def test_no_rate_in_force(repo: FakeRepository) -> None:
    with pytest.raises(NoRateError, match="No rate in force for TERM-20/agent 2 on 2023-12-31"):
        rates.resolve_rate(repo, "TERM-20", 2, date(2023, 12, 31))


@pytest.mark.rule("INS-RATE-009")
def test_rate_history_allows_repeated_supersede(repo: FakeRepository) -> None:
    rates.upsert_commission_rate(repo, "TERM-20", None, D("16"), date(2030, 1, 1), "t")
    third = rates.upsert_commission_rate(repo, "TERM-20", None, D("17"), date(2031, 1, 1), "t")
    closed = [r for r in repo.rates_for_product("TERM-20") if r.effective_to is not None]
    assert len(closed) == 2
    assert rates.resolve_rate(repo, "TERM-20", None, date(2031, 6, 1)).rate_id == third


@pytest.mark.rule("INS-RATE-010")
def test_backdated_rate_behind_later_open_rate_rejected(repo: FakeRepository) -> None:
    rates.upsert_commission_rate(repo, "TERM-20", None, D("16"), date(2030, 1, 1), "t")
    before = repo.snapshot()
    with pytest.raises(DuplicateOpenRateError):
        transactional(
            repo,
            lambda: rates.upsert_commission_rate(
                repo, "TERM-20", None, D("18"), date(2029, 1, 1), "t"
            ),
        )
    assert repo.state == before


@pytest.mark.rule("INS-RATE-011")
def test_rate_upsert_audited(repo: FakeRepository) -> None:
    rates.upsert_commission_rate(repo, "AUTO-STD", None, D("8.5"), date(2025, 7, 1), "ops")
    assert repo.state["audit"] == [
        ("RATE_UPSERT", "AUTO-STD", None, None, "rate_id=5 pct=8.5 from=2025-07-01", "ops")
    ]
