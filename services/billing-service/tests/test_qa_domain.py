"""QA audit: plain-Python domain rules for the extracted plans module."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid5

import pytest

from app.domain import (
    PLAN_CHANGE_NAMESPACE,
    EntitlementRow,
    PlanRow,
    SubscriptionRow,
    catalog,
    change_plan,
    entitlement,
)

TENANT = UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT = UUID("00000000-0000-0000-0000-000000000002")
STARTER = UUID("10000000-0000-0000-0000-000000000001")
GROWTH = UUID("10000000-0000-0000-0000-000000000002")
SCALE = UUID("10000000-0000-0000-0000-000000000003")
SUB_A = UUID("20000000-0000-0000-0000-000000000001")
SUB_B = UUID("20000000-0000-0000-0000-000000000002")


class MemoryRepository:
    def __init__(self, subscriptions: list[SubscriptionRow]) -> None:
        self.subscriptions = list(subscriptions)
        self.updates: list[tuple[UUID, date, str]] = []

    def list_subscriptions(self, tenant_id: UUID) -> list[SubscriptionRow]:
        return [item for item in self.subscriptions if item.tenant_id == tenant_id]

    def update_subscription(self, subscription_id: UUID, ends_on: date, status: str) -> None:
        self.updates.append((subscription_id, ends_on, status))
        self.subscriptions = [
            replace(item, ends_on=ends_on, status=status)
            if item.subscription_id == subscription_id
            else item
            for item in self.subscriptions
        ]

    def insert_subscription(self, subscription_id, tenant_id, plan_id, starts_on, status) -> None:
        if any(item.subscription_id == subscription_id for item in self.subscriptions):
            raise ValueError("duplicate subscription id")
        self.subscriptions.append(
            SubscriptionRow(subscription_id, tenant_id, plan_id, starts_on, None, status, None)
        )


def plan(plan_id: UUID, code: str, fee: str, active: bool = True) -> PlanRow:
    return PlanRow(plan_id, code, code.lower(), Decimal(fee), 100, Decimal("0.01"), active)


def ent(tenant: UUID, code: str, starts: date, ends: date | None = None) -> EntitlementRow:
    return EntitlementRow(tenant, code, code.lower(), Decimal("1"), 1, "active", ends, starts)


def sub(sid: UUID, plan_id: UUID, starts: date, ends=None, status="active") -> SubscriptionRow:
    return SubscriptionRow(sid, TENANT, plan_id, starts, ends, status, None)


# --- catalog ---------------------------------------------------------------


def test_catalog_excludes_inactive_plans() -> None:
    plans = [plan(STARTER, "STARTER", "49"), plan(SCALE, "LEGACY", "1", active=False)]
    assert [item.code for item in catalog(plans)] == ["STARTER"]


def test_catalog_breaks_fee_ties_by_code() -> None:
    plans = [plan(GROWTH, "ZETA", "49"), plan(STARTER, "ALPHA", "49"), plan(SCALE, "MID", "10")]
    assert [item.code for item in catalog(plans)] == ["MID", "ALPHA", "ZETA"]


def test_catalog_empty_input_returns_empty_list() -> None:
    assert catalog([]) == []


def test_catalog_does_not_mutate_input_order() -> None:
    plans = [plan(GROWTH, "GROWTH", "149"), plan(STARTER, "STARTER", "49")]
    catalog(plans)
    assert [item.code for item in plans] == ["GROWTH", "STARTER"]


# --- entitlement -------------------------------------------------------------


def test_entitlement_start_date_is_inclusive() -> None:
    row = ent(TENANT, "STARTER", date(2026, 2, 28))
    assert entitlement([row], TENANT, date(2026, 2, 28)) == row


def test_entitlement_end_date_is_inclusive() -> None:
    row = ent(TENANT, "STARTER", date(2026, 1, 1), date(2026, 2, 28))
    assert entitlement([row], TENANT, date(2026, 2, 28)) == row


def test_entitlement_excludes_ended_subscription() -> None:
    row = ent(TENANT, "STARTER", date(2026, 1, 1), date(2026, 2, 27))
    assert entitlement([row], TENANT, date(2026, 2, 28)) is None


def test_entitlement_excludes_future_subscription() -> None:
    row = ent(TENANT, "GROWTH", date(2026, 3, 1))
    assert entitlement([row], TENANT, date(2026, 2, 28)) is None


def test_entitlement_ignores_rows_for_other_tenants() -> None:
    rows = [ent(OTHER_TENANT, "SCALE", date(2026, 2, 1)), ent(TENANT, "STARTER", date(2026, 1, 1))]
    assert entitlement(rows, TENANT, date(2026, 2, 28)).plan_code == "STARTER"


def test_entitlement_prefers_latest_overlapping_start() -> None:
    rows = [ent(TENANT, "STARTER", date(2026, 1, 1)), ent(TENANT, "GROWTH", date(2026, 2, 1))]
    assert entitlement(rows, TENANT, date(2026, 2, 28)).plan_code == "GROWTH"


def test_entitlement_with_no_rows_is_none() -> None:
    assert entitlement([], TENANT, date(2026, 2, 28)) is None


# --- change_plan -------------------------------------------------------------


def test_change_plan_preserves_cancelled_status_when_closing() -> None:
    repo = MemoryRepository([sub(SUB_A, STARTER, date(2026, 1, 1), status="cancelled")])
    change_plan(repo, TENANT, GROWTH, date(2026, 3, 1))
    assert repo.updates == [(SUB_A, date(2026, 2, 28), "cancelled")]


def test_change_plan_reactivates_suspended_subscription_when_closing() -> None:
    repo = MemoryRepository([sub(SUB_A, STARTER, date(2026, 1, 1), status="suspended")])
    change_plan(repo, TENANT, GROWTH, date(2026, 3, 1))
    assert repo.updates == [(SUB_A, date(2026, 2, 28), "active")]


def test_change_plan_does_not_close_subscription_starting_same_day() -> None:
    repo = MemoryRepository([sub(SUB_A, STARTER, date(2026, 3, 1))])
    subscriptions, created = change_plan(repo, TENANT, GROWTH, date(2026, 3, 1))
    assert repo.updates == []
    assert len(subscriptions) == 2
    assert created.plan_id == GROWTH


def test_change_plan_leaves_already_closed_rows_untouched() -> None:
    repo = MemoryRepository(
        [
            sub(SUB_A, STARTER, date(2025, 1, 1), ends=date(2025, 12, 31)),
            sub(SUB_B, GROWTH, date(2026, 1, 1)),
        ]
    )
    change_plan(repo, TENANT, SCALE, date(2026, 3, 1))
    assert repo.updates == [(SUB_B, date(2026, 2, 28), "active")]


def test_change_plan_id_is_deterministic_uuid5() -> None:
    repo = MemoryRepository([sub(SUB_A, STARTER, date(2026, 1, 1))])
    _, created = change_plan(repo, TENANT, GROWTH, date(2026, 3, 1))
    expected = uuid5(PLAN_CHANGE_NAMESPACE, f"{TENANT}{GROWTH}2026-03-01")
    assert created.subscription_id == expected


def test_change_plan_result_is_sorted_by_start_date() -> None:
    repo = MemoryRepository(
        [sub(SUB_B, GROWTH, date(2026, 6, 1)), sub(SUB_A, STARTER, date(2026, 1, 1))]
    )
    subscriptions, _ = change_plan(repo, TENANT, SCALE, date(2026, 3, 1))
    starts = [item.starts_on for item in subscriptions]
    assert starts == sorted(starts)


def test_change_plan_new_subscription_is_open_ended_and_active() -> None:
    repo = MemoryRepository([])
    subscriptions, created = change_plan(repo, TENANT, STARTER, date(2026, 3, 1))
    assert created.ends_on is None
    assert created.status == "active"
    assert subscriptions == [created]


def test_change_plan_repeated_identical_request_hits_duplicate_id() -> None:
    repo = MemoryRepository([sub(SUB_A, STARTER, date(2026, 1, 1))])
    change_plan(repo, TENANT, GROWTH, date(2026, 3, 1))
    try:
        change_plan(repo, TENANT, GROWTH, date(2026, 3, 1))
    except ValueError as error:
        assert "duplicate" in str(error)
    else:  # pragma: no cover - documents the contract
        raise AssertionError("identical plan change should collide on the uuid5 id")


@pytest.mark.xfail(
    reason="QA-BILL-11: back-dated change leaves the later future-dated subscription open "
    "(parity with legacy sp_change_plan), so two open-ended subscriptions overlap",
    strict=True,
)
def test_change_plan_backdated_leaves_single_open_subscription() -> None:
    repo = MemoryRepository([sub(SUB_A, STARTER, date(2026, 1, 1))])
    change_plan(repo, TENANT, SCALE, date(2026, 7, 1))
    subscriptions, _ = change_plan(repo, TENANT, GROWTH, date(2026, 4, 1))
    assert len([item for item in subscriptions if item.ends_on is None]) == 1
