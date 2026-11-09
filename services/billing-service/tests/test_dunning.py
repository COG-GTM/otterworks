from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.dunning import (
    DunningAttempt,
    Invoice,
    next_business_day,
    overdue_accounts,
    schedule,
    suspension_notice,
    tenants_to_suspend,
)

ACTIVE = UUID("00000000-0000-0000-0000-000000000005")
SUSPENDED = UUID("00000000-0000-0000-0000-000000000002")
STATUSES = {ACTIVE: "active", SUSPENDED: "suspended"}


def invoice(number: int, tenant: UUID, issued: date, status: str = "overdue") -> Invoice:
    return Invoice(
        UUID(int=number), tenant, datetime(issued.year, issued.month, issued.day, tzinfo=UTC),
        Decimal("10.00"), status,
    )


INVOICES = [
    invoice(2, ACTIVE, date(2026, 2, 1)),
    invoice(1, SUSPENDED, date(2026, 1, 15)),
    invoice(3, ACTIVE, date(2026, 2, 28)),
    invoice(4, ACTIVE, date(2026, 1, 1), status="paid"),
]


@pytest.mark.rule("DUNNING-001")
def test_overdue_accounts_are_oldest_first_and_before_as_of() -> None:
    rows = overdue_accounts(INVOICES, STATUSES, date(2026, 2, 28))
    assert [(row.invoice_id.int, row.days_overdue, row.tenant_status) for row in rows] == [
        (1, 44, "suspended"),
        (2, 27, "active"),
    ]


@pytest.mark.rule("DUNNING-002")
def test_weekend_attempts_move_to_monday() -> None:
    assert next_business_day(date(2026, 2, 14)) == date(2026, 2, 16)
    assert next_business_day(date(2026, 2, 15)) == date(2026, 2, 16)
    assert next_business_day(date(2026, 2, 17)) == date(2026, 2, 17)
    created = schedule(INVOICES, [], date(2026, 2, 14))
    assert {item.scheduled_for for item in created} == {date(2026, 2, 16)}
    assert {item.status for item in created} == {"scheduled"}


@pytest.mark.rule("DUNNING-003")
def test_each_overdue_invoice_gets_next_attempt_number() -> None:
    existing = [
        DunningAttempt(UUID(int=90), ACTIVE, UUID(int=2), 1, date(2026, 2, 16), "sent"),
        DunningAttempt(UUID(int=91), ACTIVE, UUID(int=2), 2, date(2026, 2, 17), "scheduled"),
    ]
    created = schedule(INVOICES, existing, date(2026, 2, 17))
    assert [(item.invoice_id.int, item.attempt_no) for item in created] == [(1, 1), (2, 3), (3, 1)]


@pytest.mark.rule("DUNNING-004")
def test_only_active_tenants_overdue_fourteen_days_are_suspended() -> None:
    assert tenants_to_suspend(INVOICES, STATUSES, date(2026, 2, 15)) == [ACTIVE]
    assert tenants_to_suspend(INVOICES, STATUSES, date(2026, 2, 14)) == []


@pytest.mark.rule("DUNNING-005")
def test_suspension_notice_is_stable_per_tenant_and_date() -> None:
    first = suspension_notice(ACTIVE, date(2026, 2, 28))
    assert first == suspension_notice(ACTIVE, date(2026, 2, 28))
    assert str(first.notification_id) == "8cd558f5-d843-8d3d-be19-fb94c21ab81f"
    assert first.sent_at == datetime(2026, 2, 28, tzinfo=UTC)
