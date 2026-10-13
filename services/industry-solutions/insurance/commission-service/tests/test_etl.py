from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.domain.calculation import calculate_policy_commission
from app.domain.etl import load_commission_facts, period_dim, summarize
from tests.fakes import FakeRepository


def _calc_june(repo: FakeRepository) -> None:
    for policy_id in (1, 2, 4):
        calculate_policy_commission(repo, policy_id, "2025-06", "t")


@pytest.mark.rule("INS-ETL-001")
def test_dimensions_upserted_from_oltp(repo: FakeRepository) -> None:
    load_commission_facts(repo, None)
    assert set(repo.state["dim_agent"]) == {1, 2, 3, 4}
    assert set(repo.state["dim_product"]) == {"AUTO-STD", "HOME-PLUS", "TERM-20"}
    assert period_dim("2025-11").quarter_num == 4
    assert period_dim("2025-01").quarter_num == 1


@pytest.mark.rule("INS-ETL-002")
def test_facts_merge_idempotently_and_reconcile(repo: FakeRepository) -> None:
    _calc_june(repo)
    assert load_commission_facts(repo, "2025-06") == 6
    assert load_commission_facts(repo, "2025-06") == 6
    facts = repo.state["facts"]
    assert len(facts) == 6
    ledger_total = sum(r.commission_amt for r in repo.state["ledger"].values())
    assert sum(f.commission_amt for f in facts.values()) == ledger_total == D("104.25")


@pytest.mark.rule("INS-ETL-003")
def test_period_filter_limits_load(repo: FakeRepository) -> None:
    _calc_june(repo)
    calculate_policy_commission(repo, 1, "2025-07", "t")
    assert load_commission_facts(repo, "2025-07") == 1
    assert set(repo.state["dim_period"]) == {"2025-07"}
    assert load_commission_facts(repo, None) == 7


@pytest.mark.rule("INS-ETL-004")
def test_stale_facts_are_not_deleted(repo: FakeRepository) -> None:
    calculate_policy_commission(repo, 2, "2025-06", "t")
    load_commission_facts(repo, "2025-06")
    repo.replace_splits(2, repo.list_splits(2)[:1])
    repo.state["splits"][2] = [type(repo.list_splits(2)[0])(1, D("100.00"))]
    calculate_policy_commission(repo, 2, "2025-06", "t")
    assert load_commission_facts(repo, "2025-06") == 1
    assert sorted(k[1] for k in repo.state["facts"]) == [1, 2]


@pytest.mark.rule("INS-ETL-005")
def test_summary_groups_by_agent_period_lob(repo: FakeRepository) -> None:
    _calc_june(repo)
    load_commission_facts(repo, "2025-06")
    rows = summarize(
        list(repo.state["facts"].values()), repo.state["dim_agent"], repo.state["dim_product"]
    )
    assert [
        (r.agent_code, r.line_of_business, r.policy_rows, r.total_commission) for r in rows
    ] == [
        ("AG-100", "AUTO", 2, D("52.25")),
        ("AG-100", "HOME", 1, D("12.00")),
        ("AG-101", "AUTO", 1, D("19.20")),
        ("AG-101", "HOME", 1, D("8.00")),
        ("AG-102", "AUTO", 1, D("12.80")),
    ]
