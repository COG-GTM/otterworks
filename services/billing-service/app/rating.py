from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.domain import PlanRow, SubscriptionRow
from app.money import md5_uuid, round_money, round_units, subtract_months, utc_date

FIRST_TIER_UNITS = 101
SECOND_TIER_MULTIPLIER = Decimal("1.5")
ROLLOVER_WINDOW_MONTHS = 3


@dataclass(frozen=True)
class UsageEvent:
    tenant_id: UUID
    occurred_at: datetime
    units: int
    kind: str


@dataclass(frozen=True)
class PriorRollover:
    period_start: date
    rollover_units: int


@dataclass(frozen=True)
class Rating:
    tenant_id: UUID
    period_start: date
    period_end: date
    used_units: int
    quota_units: int
    rollover_units: int
    billable_units: int
    first_tier_units: int
    second_tier_units: int
    overage_amount: Decimal


@dataclass(frozen=True)
class UsageKindSummary:
    kind: str
    event_count: int
    units: int


@dataclass(frozen=True)
class FinalizedRating:
    period_id: UUID
    result_id: UUID
    subscription_id: UUID
    used_units: int
    quota_units: int
    rollover_units: int
    billable_units: int
    overage_amount: Decimal


def period_id(tenant_id: UUID, period_start: date) -> UUID:
    return md5_uuid(f"{tenant_id}{period_start.isoformat()}")


def subscription_for_period(
    subscriptions: list[SubscriptionRow], period_start: date, period_end: date
) -> SubscriptionRow | None:
    eligible = [
        item
        for item in subscriptions
        if item.starts_on <= period_end and (item.ends_on is None or item.ends_on >= period_start)
    ]
    return max(eligible, key=lambda item: item.starts_on, default=None)


def events_in_period(
    events: list[UsageEvent], period_start: date, period_end: date
) -> list[UsageEvent]:
    return [item for item in events if period_start <= utc_date(item.occurred_at) <= period_end]


def rate_usage(
    tenant_id: UUID,
    subscription: SubscriptionRow,
    plan: PlanRow,
    events: list[UsageEvent],
    prior: list[PriorRollover],
    period_start: date,
    period_end: date,
) -> Rating:
    used = sum(item.units for item in events_in_period(events, period_start, period_end))
    window_start = subtract_months(period_start, ROLLOVER_WINDOW_MONTHS)
    prior_units = sum(
        item.rollover_units
        for item in prior
        if window_start <= item.period_start < period_start
    )
    rollover_cap = 2 * plan.included_units
    rollover = min(prior_units, rollover_cap)
    billable = max(used - rollover - plan.included_units, 0)
    first = min(billable, FIRST_TIER_UNITS)
    second = max(billable - FIRST_TIER_UNITS, 0)
    amount = round_money(
        first * plan.overage_rate + second * plan.overage_rate * SECOND_TIER_MULTIPLIER
    )
    suspended_on = subscription.suspended_on
    if (
        subscription.status == "suspended"
        and suspended_on is not None
        and period_start <= suspended_on <= period_end
    ):
        share = Decimal((period_end - suspended_on).days + 1) / Decimal(
            (period_end - period_start).days + 1
        )
        billable = round_units(billable * share)
        amount = round_money(amount * share)
    return Rating(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
        used_units=used,
        quota_units=plan.included_units,
        rollover_units=rollover,
        billable_units=billable,
        first_tier_units=first,
        second_tier_units=second,
        overage_amount=amount,
    )


def summarize_usage(
    events: list[UsageEvent], period_start: date, period_end: date
) -> list[UsageKindSummary]:
    totals: dict[str, tuple[int, int]] = {}
    for item in events_in_period(events, period_start, period_end):
        count, units = totals.get(item.kind, (0, 0))
        totals[item.kind] = (count + 1, units + item.units)
    return [UsageKindSummary(kind, count, units) for kind, (count, units) in sorted(totals.items())]


def finalize(
    tenant_id: UUID, subscription: SubscriptionRow, rating: Rating
) -> FinalizedRating:
    rating_period_id = period_id(tenant_id, rating.period_start)
    return FinalizedRating(
        period_id=rating_period_id,
        result_id=md5_uuid(str(rating_period_id)),
        subscription_id=subscription.subscription_id,
        used_units=rating.used_units,
        quota_units=rating.quota_units,
        rollover_units=max(rating.quota_units - rating.used_units, 0),
        billable_units=rating.billable_units,
        overage_amount=rating.overage_amount,
    )
