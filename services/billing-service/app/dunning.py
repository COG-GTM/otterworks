from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.money import md5_uuid, utc_date, utc_midnight

SUSPENSION_GRACE_DAYS = 14


@dataclass(frozen=True)
class Invoice:
    invoice_id: UUID
    tenant_id: UUID
    issued_at: datetime
    total: Decimal
    status: str


@dataclass(frozen=True)
class OverdueAccount:
    tenant_id: UUID
    invoice_id: UUID
    total: Decimal
    days_overdue: int
    tenant_status: str


@dataclass(frozen=True)
class DunningAttempt:
    attempt_id: UUID
    tenant_id: UUID
    invoice_id: UUID
    attempt_no: int
    scheduled_for: date
    status: str


@dataclass(frozen=True)
class SuspensionNotice:
    notification_id: UUID
    tenant_id: UUID
    sent_at: datetime


def overdue_in_order(invoices: list[Invoice]) -> list[Invoice]:
    return sorted(
        (item for item in invoices if item.status == "overdue"),
        key=lambda item: (item.issued_at, item.invoice_id),
    )


def overdue_accounts(
    invoices: list[Invoice], tenant_statuses: dict[UUID, str], as_of: date
) -> list[OverdueAccount]:
    return [
        OverdueAccount(
            tenant_id=item.tenant_id,
            invoice_id=item.invoice_id,
            total=item.total,
            days_overdue=(as_of - utc_date(item.issued_at)).days,
            tenant_status=tenant_statuses[item.tenant_id],
        )
        for item in overdue_in_order(invoices)
        if utc_date(item.issued_at) < as_of
    ]


def next_business_day(as_of: date) -> date:
    weekday = as_of.isoweekday()
    if weekday == 6:
        return as_of + timedelta(days=2)
    if weekday == 7:
        return as_of + timedelta(days=1)
    return as_of


def schedule(
    invoices: list[Invoice], attempts: list[DunningAttempt], as_of: date
) -> list[DunningAttempt]:
    scheduled_for = next_business_day(as_of)
    created = []
    for invoice in overdue_in_order(invoices):
        attempt_no = (
            max(
                (item.attempt_no for item in attempts if item.invoice_id == invoice.invoice_id),
                default=0,
            )
            + 1
        )
        created.append(
            DunningAttempt(
                attempt_id=md5_uuid(f"{invoice.invoice_id}{attempt_no}"),
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.invoice_id,
                attempt_no=attempt_no,
                scheduled_for=scheduled_for,
                status="scheduled",
            )
        )
    return created


def tenants_to_suspend(
    invoices: list[Invoice], tenant_statuses: dict[UUID, str], as_of: date
) -> list[UUID]:
    cutoff = as_of - timedelta(days=SUSPENSION_GRACE_DAYS)
    overdue_tenants = {
        item.tenant_id
        for item in invoices
        if item.status == "overdue" and utc_date(item.issued_at) <= cutoff
    }
    return sorted(
        tenant_id for tenant_id in overdue_tenants if tenant_statuses.get(tenant_id) == "active"
    )


def suspension_notice(tenant_id: UUID, as_of: date) -> SuspensionNotice:
    return SuspensionNotice(
        notification_id=md5_uuid(f"{tenant_id}suspension{as_of.isoformat()}"),
        tenant_id=tenant_id,
        sent_at=utc_midnight(as_of),
    )
