from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.domain.errors import BadSplitError, InactiveAgentError, UnknownPolicyError
from app.domain.model import Split
from app.domain.splits import set_commission_splits
from tests.fakes import FakeRepository


@pytest.mark.rule("INS-SPLIT-001")
def test_unknown_policy_rejected(repo: FakeRepository) -> None:
    with pytest.raises(UnknownPolicyError, match="Unknown policy: 99") as err:
        set_commission_splits(repo, 99, [(1, D("100"))], "t")
    assert err.value.ora_code == -20005


@pytest.mark.rule("INS-SPLIT-002")
def test_empty_allocation_rejected(repo: FakeRepository) -> None:
    with pytest.raises(BadSplitError, match="At least one split allocation is required"):
        set_commission_splits(repo, 3, [], "t")


@pytest.mark.rule("INS-SPLIT-003")
def test_duplicate_agent_rejected(repo: FakeRepository) -> None:
    with pytest.raises(BadSplitError, match="Duplicate agent in split allocation"):
        set_commission_splits(repo, 3, [(1, D("50")), (1, D("50"))], "t")


@pytest.mark.rule("INS-SPLIT-004")
@pytest.mark.parametrize("pct", [D("0"), D("-5"), D("100.01"), None])
def test_each_split_in_range(repo: FakeRepository, pct: D | None) -> None:
    with pytest.raises(BadSplitError, match=r"Split pct must be in \(0, 100\]: agent 2"):
        set_commission_splits(repo, 3, [(2, pct)], "t")


@pytest.mark.rule("INS-SPLIT-005")
def test_inactive_agent_rejected(repo: FakeRepository) -> None:
    with pytest.raises(InactiveAgentError, match="Agent 4 is SUSPENDED"):
        set_commission_splits(repo, 3, [(1, D("50")), (4, D("50"))], "t")


@pytest.mark.rule("INS-SPLIT-006")
def test_total_must_be_exactly_100(repo: FakeRepository) -> None:
    with pytest.raises(BadSplitError, match="must total 100.00, got 110"):
        set_commission_splits(repo, 3, [(1, D("60")), (2, D("50"))], "t")
    with pytest.raises(BadSplitError, match="got 99.5"):
        set_commission_splits(repo, 3, [(1, D("59.5")), (2, D("40"))], "t")


@pytest.mark.rule("INS-SPLIT-006")
def test_total_uses_raw_values_storage_rounds(repo: FakeRepository) -> None:
    stored = set_commission_splits(repo, 3, [(1, D("33.333")), (2, D("66.667"))], "t")
    assert stored == [Split(1, D("33.33")), Split(2, D("66.67"))]


@pytest.mark.rule("INS-SPLIT-007")
def test_valid_split_replaces_and_audits(repo: FakeRepository) -> None:
    set_commission_splits(repo, 2, [(3, D("70")), (2, D("30"))], "mgr")
    assert repo.list_splits(2) == [Split(3, D("70.00")), Split(2, D("30.00"))]
    assert repo.state["audit"] == [("SPLIT_SET", None, None, 2, "2 agents", "mgr")]
