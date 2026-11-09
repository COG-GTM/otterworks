from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, model_validator

from app import dunning, invoicing, rating
from app.billing_repository import PostgresBillingRepository
from app.db import connect
from app.domain import PlanRow, SubscriptionRow
from app.money import utc_midnight
from app.repository import PostgresPlansRepository

router = APIRouter(prefix="/api")


class BillingPeriod(BaseModel):
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def ordered(self) -> BillingPeriod:
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class AsOf(BaseModel):
    as_of: date


def money(value: Decimal) -> str:
    return format(value, "f")


def iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        utc = value.astimezone(UTC).isoformat(timespec="seconds")
        return utc.replace("+00:00", "Z")
    return value.isoformat()


def period(period_start: date, period_end: date) -> BillingPeriod:
    try:
        return BillingPeriod(period_start=period_start, period_end=period_end)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def rated_period(
    connection: psycopg.Connection, tenant_id: UUID, billing_period: BillingPeriod
) -> tuple[SubscriptionRow, PlanRow, rating.Rating]:
    plans_repository = PostgresPlansRepository(connection)
    billing_repository = PostgresBillingRepository(connection)
    subscription = rating.subscription_for_period(
        plans_repository.list_subscriptions(tenant_id),
        billing_period.period_start,
        billing_period.period_end,
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="no subscription covers this period")
    plan = next(
        item for item in plans_repository.list_plans() if item.plan_id == subscription.plan_id
    )
    result = rating.rate_usage(
        tenant_id,
        subscription,
        plan,
        billing_repository.usage_events(tenant_id),
        billing_repository.prior_rollovers(tenant_id),
        billing_period.period_start,
        billing_period.period_end,
    )
    return subscription, plan, result


def rating_payload(result: rating.Rating) -> dict:
    return {
        "tenant_id": str(result.tenant_id),
        "period_start": iso(result.period_start),
        "period_end": iso(result.period_end),
        "used_units": result.used_units,
        "quota_units": result.quota_units,
        "rollover_units": result.rollover_units,
        "billable_units": result.billable_units,
        "first_tier_units": result.first_tier_units,
        "second_tier_units": result.second_tier_units,
        "overage_amount": money(result.overage_amount),
    }


def finalize_rating(
    connection: psycopg.Connection, tenant_id: UUID, billing_period: BillingPeriod
) -> rating.FinalizedRating:
    subscription, _plan, result = rated_period(connection, tenant_id, billing_period)
    finalized = rating.finalize(tenant_id, subscription, result)
    PostgresBillingRepository(connection).save_rating(
        tenant_id, billing_period.period_start, billing_period.period_end, finalized
    )
    return finalized


def preview_lines(
    connection: psycopg.Connection, tenant_id: UUID, billing_period: BillingPeriod
) -> list[invoicing.PreviewLine]:
    repository = PostgresBillingRepository(connection)
    profile = repository.tenant_profile(tenant_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    _subscription, plan, result = rated_period(connection, tenant_id, billing_period)
    return invoicing.preview(
        plan, result, profile["tax_exempt"], repository.credit_notes(tenant_id)
    )


@router.get("/tenants/{tenant_id}/usage-rating")
def get_usage_rating(
    tenant_id: Annotated[UUID, Path()],
    period_start: Annotated[date, Query()],
    period_end: Annotated[date, Query()],
) -> dict:
    with connect() as connection:
        _subscription, _plan, result = rated_period(
            connection, tenant_id, period(period_start, period_end)
        )
    return rating_payload(result)


@router.get("/tenants/{tenant_id}/usage-summary")
def get_usage_summary(
    tenant_id: Annotated[UUID, Path()],
    period_start: Annotated[date, Query()],
    period_end: Annotated[date, Query()],
) -> list[dict]:
    billing_period = period(period_start, period_end)
    with connect() as connection:
        events = PostgresBillingRepository(connection).usage_events(tenant_id)
    return [
        {"kind": item.kind, "event_count": item.event_count, "units": item.units}
        for item in rating.summarize_usage(
            events, billing_period.period_start, billing_period.period_end
        )
    ]


@router.post("/tenants/{tenant_id}/rating-periods")
def post_finalize_rating(tenant_id: Annotated[UUID, Path()], request: BillingPeriod) -> dict:
    with connect() as connection:
        finalized = finalize_rating(connection, tenant_id, request)
        results = PostgresBillingRepository(connection).rating_results(
            tenant_id, request.period_start
        )
    rows = [
        {
            "used_units": row["used_units"],
            "quota_units": row["quota_units"],
            "rollover_units": row["rollover_units"],
            "billable_units": row["billable_units"],
            "overage_amount": money(row["overage_amount"]),
        }
        for row in results
    ]
    return {
        "period_id": str(finalized.period_id),
        "result": {
            "used_units": finalized.used_units,
            "quota_units": finalized.quota_units,
            "rollover_units": finalized.rollover_units,
            "billable_units": finalized.billable_units,
            "overage_amount": money(finalized.overage_amount),
        },
        "rating_results": rows,
    }


@router.get("/tenants/{tenant_id}/invoice-preview")
def get_invoice_preview(
    tenant_id: Annotated[UUID, Path()],
    period_start: Annotated[date, Query()],
    period_end: Annotated[date, Query()],
) -> list[dict]:
    with connect() as connection:
        lines = preview_lines(connection, tenant_id, period(period_start, period_end))
    return [
        {
            "line_no": line.line_no,
            "line_type": line.line_type,
            "description": line.description,
            "amount": money(line.amount),
            "tax_amount": money(line.tax_amount),
            "credit_applied": money(line.credit_applied),
            "total": money(line.total),
        }
        for line in lines
    ]


@router.post("/tenants/{tenant_id}/invoices")
def post_issue_invoice(tenant_id: Annotated[UUID, Path()], request: BillingPeriod) -> dict:
    try:
        with connect() as connection:
            repository = PostgresBillingRepository(connection)
            repository.lock_credit_notes(tenant_id)
            finalized = finalize_rating(connection, tenant_id, request)
            lines = preview_lines(connection, tenant_id, request)
            issued = invoicing.issue(
                finalized.period_id, lines, repository.credit_notes(tenant_id)
            )
            repository.save_invoice(
                tenant_id, finalized.period_id, utc_midnight(request.period_end), issued
            )
            invoices = repository.period_invoices(finalized.period_id)
            credits = repository.credit_notes(tenant_id)
    except psycopg.errors.CheckViolation as error:
        raise HTTPException(status_code=409, detail="invoice totals are inconsistent") from error
    current = next(row for row in invoices if row["id"] == issued.invoice_id)
    return {
        "invoice_id": str(issued.invoice_id),
        "invoice": invoice_payload(current),
        "invoices": [invoice_payload(row) for row in invoices],
        "lines": [line_payload(line) for line in issued.lines],
        "credit_notes": [
            {
                "id": str(item.credit_id),
                "issued_on": iso(item.issued_on),
                "remaining_amount": money(item.remaining_amount),
            }
            for item in credits
        ],
    }


def invoice_payload(row: dict) -> dict:
    return {
        "status": row["status"],
        "subtotal": money(row["subtotal"]),
        "tax": money(row["tax"]),
        "total": money(row["total"]),
    }


def line_payload(line: invoicing.InvoiceLine) -> dict:
    return {
        "line_no": line.line_no,
        "line_type": line.line_type,
        "description": line.description,
        "amount": money(line.amount),
    }


@router.get("/invoices/{invoice_id}/lines")
def get_invoice_lines(invoice_id: Annotated[UUID, Path()]) -> list[dict]:
    with connect() as connection:
        lines = PostgresBillingRepository(connection).invoice_lines(invoice_id)
    return [line_payload(line) for line in lines]


@router.get("/dunning/overdue")
def get_overdue_accounts(as_of: Annotated[date, Query()]) -> list[dict]:
    with connect() as connection:
        repository = PostgresBillingRepository(connection)
        accounts = dunning.overdue_accounts(
            repository.invoices(), repository.tenant_statuses(), as_of
        )
    return [
        {
            "tenant_id": str(item.tenant_id),
            "invoice_id": str(item.invoice_id),
            "total": money(item.total),
            "days_overdue": item.days_overdue,
            "tenant_status": item.tenant_status,
        }
        for item in accounts
    ]


def attempt_payload(item: dunning.DunningAttempt) -> dict:
    return {
        "invoice_id": str(item.invoice_id),
        "attempt_no": item.attempt_no,
        "scheduled_for": iso(item.scheduled_for),
        "status": item.status,
    }


@router.post("/dunning/schedule")
def post_schedule_dunning(request: AsOf) -> dict:
    with connect() as connection:
        repository = PostgresBillingRepository(connection)
        created = dunning.schedule(
            repository.invoices(), repository.dunning_attempts(), request.as_of
        )
        for attempt in created:
            repository.insert_dunning_attempt(attempt)
        attempts = repository.dunning_attempts()
    return {
        "scheduled_for": iso(dunning.next_business_day(request.as_of)),
        "scheduled": [attempt_payload(item) for item in created],
        "attempts": [attempt_payload(item) for item in attempts],
    }


@router.post("/dunning/suspend")
def post_suspend_overdue(request: AsOf) -> dict:
    with connect() as connection:
        repository = PostgresBillingRepository(connection)
        tenants = dunning.tenants_to_suspend(
            repository.invoices(), repository.tenant_statuses(), request.as_of
        )
        subscriptions = []
        for tenant_id in tenants:
            subscriptions.extend(repository.suspend_tenant(tenant_id, request.as_of))
            repository.insert_suspension_notice(
                dunning.suspension_notice(tenant_id, request.as_of)
            )
        notifications = repository.suspension_notifications()
    return {
        "suspended_tenants": [str(item) for item in tenants],
        "subscriptions": [
            {
                "tenant_id": str(row["tenant_id"]),
                "subscription_id": str(row["id"]),
                "status": row["status"],
                "suspended_on": iso(row["suspended_on"]),
            }
            for row in subscriptions
        ],
        "suspension_notifications": [
            {
                "id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "kind": row["kind"],
                "sent_at": iso(row["sent_at"]),
            }
            for row in notifications
        ],
    }
