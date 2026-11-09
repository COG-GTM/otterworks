from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain import PlanRow, SubscriptionRow
from app.rating import (
    PriorRollover,
    UsageEvent,
    finalize,
    period_id,
    rate_usage,
    subscription_for_period,
    summarize_usage,
)

TENANT = UUID("00000000-0000-0000-0000-000000000001")
PLAN = PlanRow(
    plan_id=UUID("10000000-0000-0000-0000-000000000002"),
    code="GROWTH",
    tier="growth",
    monthly_fee=Decimal("99.00"),
    included_units=500,
    overage_rate=Decimal("0.035000"),
    active=True,
)
START, END = date(2026, 2, 1), date(2026, 2, 28)


def subscription(**changes) -> SubscriptionRow:
    values = {
        "subscription_id": UUID("20000000-0000-0000-0000-000000000001"),
        "tenant_id": TENANT,
        "plan_id": PLAN.plan_id,
        "starts_on": date(2026, 1, 1),
        "ends_on": None,
        "status": "active",
        "suspended_on": None,
    }
    values.update(changes)
    return SubscriptionRow(**values)


def event(day: date, units: int, kind: str = "api", hour: int = 10) -> UsageEvent:
    return UsageEvent(TENANT, datetime(day.year, day.month, day.day, hour, tzinfo=UTC), units, kind)


def rate(units: int, prior: list[PriorRollover] | None = None, **changes):
    return rate_usage(
        TENANT, subscription(**changes), PLAN, [event(date(2026, 2, 10), units)], prior or [],
        START, END,
    )


@pytest.mark.rule("RATING-001")
def test_usage_counts_only_events_in_period_for_covering_subscription() -> None:
    events = [
        event(date(2026, 1, 31), 50, hour=23),
        event(date(2026, 2, 1), 100, hour=0),
        event(date(2026, 2, 28), 40, hour=23),
        event(date(2026, 3, 1), 70),
    ]
    result = rate_usage(TENANT, subscription(), PLAN, events, [], START, END)
    assert result.used_units == 140
    assert result.quota_units == 500

    older = subscription(starts_on=date(2025, 1, 1), ends_on=date(2026, 2, 9))
    newer = subscription(subscription_id=UUID(int=2), starts_on=date(2026, 2, 10))
    ended = subscription(subscription_id=UUID(int=3), ends_on=date(2026, 1, 31))
    assert subscription_for_period([older, newer, ended], START, END) == newer


@pytest.mark.rule("RATING-002")
def test_rollover_uses_three_month_window_capped_at_twice_quota() -> None:
    prior = [
        PriorRollover(date(2025, 10, 1), 400),
        PriorRollover(date(2025, 11, 1), 300),
        PriorRollover(date(2025, 12, 1), 400),
        PriorRollover(date(2026, 1, 1), 400),
        PriorRollover(date(2026, 2, 1), 999),
    ]
    result = rate(1600, prior)
    assert result.rollover_units == 1000
    assert result.billable_units == 100


@pytest.mark.rule("RATING-003")
def test_suspension_inside_period_prorates_units_and_amount() -> None:
    result = rate(700, status="suspended", suspended_on=date(2026, 2, 15))
    assert result.billable_units == 100
    assert result.overage_amount == Decimal("4.37")

    outside = rate(700, status="suspended", suspended_on=date(2026, 1, 15))
    assert outside.billable_units == 200


@pytest.mark.rule("RATING-004")
def test_overage_tiers_split_at_101_units() -> None:
    boundary = rate(601)
    assert (boundary.first_tier_units, boundary.second_tier_units) == (101, 0)
    assert boundary.overage_amount == Decimal("3.54")

    beyond = rate(602)
    assert (beyond.first_tier_units, beyond.second_tier_units) == (101, 1)
    assert beyond.overage_amount == Decimal("3.59")


@pytest.mark.rule("RATING-005")
def test_usage_summary_groups_by_kind_in_kind_order() -> None:
    events = [
        event(date(2026, 2, 3), 5, "storage"),
        event(date(2026, 2, 4), 7, "api"),
        event(date(2026, 2, 5), 3, "storage"),
        event(date(2026, 3, 5), 9, "compute"),
    ]
    rows = [(row.kind, row.event_count, row.units) for row in summarize_usage(events, START, END)]
    assert rows == [("api", 1, 7), ("storage", 2, 8)]


@pytest.mark.rule("RATING-006")
def test_finalize_records_unused_quota_as_rollover_with_legacy_ids() -> None:
    finalized = finalize(TENANT, subscription(), rate(260))
    assert finalized.rollover_units == 240
    assert finalized.billable_units == 0
    assert finalized.period_id == period_id(TENANT, START)
    assert str(finalized.period_id) == "27cdd7d2-32b3-afc0-922c-e9858e767b6d"

    over = finalize(TENANT, subscription(), rate(800))
    assert over.rollover_units == 0
