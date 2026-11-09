from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain import PlanRow
from app.invoicing import CreditNote, InvoiceLine, issue, preview
from app.rating import Rating

TENANT = UUID("00000000-0000-0000-0000-000000000006")
PERIOD = UUID("27cdd7d2-32b3-afc0-922c-e9858e767b6d")
PLAN = PlanRow(
    plan_id=UUID("10000000-0000-0000-0000-000000000001"),
    code="STARTER",
    tier="starter",
    monthly_fee=Decimal("49.00"),
    included_units=100,
    overage_rate=Decimal("0.055000"),
    active=True,
)


def rating(overage: str) -> Rating:
    return Rating(TENANT, date(2026, 2, 1), date(2026, 2, 28), 201, 100, 0, 101, 101, 0,
                  Decimal(overage))


def credit(number: int, issued_on: date, remaining: str) -> CreditNote:
    return CreditNote(UUID(int=number), issued_on, Decimal(remaining))


@pytest.mark.rule("INVOICE-001")
def test_preview_splits_tax_and_caps_credit_at_gross() -> None:
    lines = preview(PLAN, rating("5.56"), False, [credit(1, date(2026, 1, 1), "100.00")])
    assert [line.line_type for line in lines] == ["plan", "usage", "tax", "tax", "credit"]
    assert [line.total for line in lines[:2]] == [Decimal("49.00"), Decimal("5.56")]
    assert lines[2].amount == lines[3].amount == Decimal("2.2506")
    assert lines[4].credit_applied == Decimal("59.06")
    assert lines[4].total == Decimal("-59.06")


@pytest.mark.rule("INVOICE-002")
def test_tax_exempt_tenant_previews_zero_tax() -> None:
    lines = preview(PLAN, rating("5.56"), True, [])
    assert [line.amount for line in lines if line.line_type == "tax"] == [0, 0]
    assert all(line.tax_amount == 0 for line in lines)
    assert lines[4].credit_applied == 0


@pytest.mark.rule("INVOICE-003")
def test_issue_consumes_oldest_credit_first_then_by_id() -> None:
    credits = [
        credit(3, date(2026, 1, 20), "50.00"),
        credit(2, date(2026, 1, 5), "30.00"),
        credit(1, date(2026, 1, 5), "10.00"),
        credit(4, date(2026, 1, 1), "0.00"),
    ]
    lines = preview(PLAN, rating("0.00"), True, credits)
    issued = issue(PERIOD, lines, credits)
    assert issued.credit_balances == {
        UUID(int=1): Decimal("0.00"),
        UUID(int=2): Decimal("0.00"),
        UUID(int=3): Decimal("41.00"),
    }
    assert issued.total == Decimal("0.00")


@pytest.mark.rule("INVOICE-004")
def test_issue_rounds_each_line_and_nets_credit() -> None:
    lines = preview(PLAN, rating("5.56"), False, [credit(1, date(2026, 1, 1), "10.00")])
    issued = issue(PERIOD, lines, [credit(1, date(2026, 1, 1), "10.00")])
    assert issued.subtotal == Decimal("54.56")
    assert issued.tax == Decimal("4.50")
    assert issued.total == Decimal("49.06")
    assert str(issued.invoice_id) == "109bb68d-8fc1-401b-9a8a-fa89e98e2388"
    assert [line.amount for line in issued.lines] == [
        Decimal("49.00"), Decimal("5.56"), Decimal("2.25"), Decimal("2.25"), Decimal("-10.00"),
    ]


@pytest.mark.rule("INVOICE-005")
def test_issued_lines_keep_line_number_order_and_stable_ids() -> None:
    issued = issue(PERIOD, preview(PLAN, rating("0.00"), True, []), [])
    assert [line.line_no for line in issued.lines] == [1, 2, 3, 4, 5]
    assert all(isinstance(line, InvoiceLine) for line in issued.lines)
    assert len({line.line_id for line in issued.lines}) == 5
