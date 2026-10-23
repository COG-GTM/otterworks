"""Stored-procedure unit tests against the legacy billing schema.

Every test runs inside a transaction that is rolled back (see conftest.db).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import GROWTH, SCALE, STARTER, TENANT, query

PERIOD = ("2026-02-01", "2026-02-28")
QA_TENANT = "00000000-0000-0000-0000-0000000000aa"


def rating(db, tenant: str) -> dict:
    return query(db, "SELECT * FROM billing.fn_usage_rating(%s, %s, %s)", (tenant, *PERIOD))[0]


def preview(db, tenant: str) -> list[dict]:
    return query(db, "SELECT * FROM billing.fn_invoice_preview(%s, %s, %s)", (tenant, *PERIOD))


def make_tenant(db, plan_id: str, *, tax_exempt: bool = False) -> None:
    query(
        db,
        "INSERT INTO billing.tenants VALUES (%s, 'QA tenant', %s, 'active')",
        (QA_TENANT, tax_exempt),
    )
    query(
        db,
        "INSERT INTO billing.subscriptions VALUES "
        "('20000000-0000-0000-0000-0000000000aa', %s, %s, '2026-01-01', NULL, 'active', NULL)",
        (QA_TENANT, plan_id),
    )


# --- plans -------------------------------------------------------------------


def test_list_plans_is_fee_ordered(db) -> None:
    rows = query(db, "SELECT code, monthly_fee FROM billing.fn_list_plans()")
    assert [row["code"] for row in rows] == ["STARTER", "GROWTH", "SCALE"]
    assert [row["monthly_fee"] for row in rows] == sorted(row["monthly_fee"] for row in rows)


def test_list_plans_hides_inactive(db) -> None:
    query(db, "UPDATE billing.plans SET active = false WHERE id = %s", (SCALE,))
    rows = query(db, "SELECT code FROM billing.fn_list_plans()")
    assert "SCALE" not in [row["code"] for row in rows]


def test_entitlement_tenant_one_is_starter(db) -> None:
    rows = query(db, "SELECT * FROM billing.fn_entitlement(%s, %s)", (TENANT[1], "2026-02-28"))
    assert len(rows) == 1
    assert rows[0]["plan_code"] == "STARTER"
    assert rows[0]["included_units"] == 100


def test_entitlement_suspended_tenant(db) -> None:
    rows = query(db, "SELECT * FROM billing.fn_entitlement(%s, %s)", (TENANT[2], "2026-02-28"))
    assert rows[0]["subscription_status"] == "suspended"


def test_entitlement_unknown_tenant_is_empty(db) -> None:
    rows = query(db, "SELECT * FROM billing.fn_entitlement(%s, %s)", (QA_TENANT, "2026-02-28"))
    assert rows == []


def test_change_plan_closes_prior_and_opens_new(db) -> None:
    query(db, "CALL billing.sp_change_plan(%s, %s, %s)", (TENANT[1], GROWTH, "2026-03-01"))
    subs = query(
        db,
        "SELECT plan_id::text, starts_on, ends_on FROM billing.subscriptions "
        "WHERE tenant_id = %s ORDER BY starts_on",
        (TENANT[1],),
    )
    assert subs[-2]["ends_on"] == date(2026, 2, 28)
    assert subs[-1] == {"plan_id": GROWTH, "starts_on": date(2026, 3, 1), "ends_on": None}
    after = query(
        db, "SELECT plan_code FROM billing.fn_entitlement(%s, %s)", (TENANT[1], "2026-03-01")
    )
    assert after[0]["plan_code"] == "GROWTH"
    before = query(
        db, "SELECT plan_code FROM billing.fn_entitlement(%s, %s)", (TENANT[1], "2026-02-28")
    )
    assert before[0]["plan_code"] == "STARTER"


def test_change_plan_unknown_plan_is_rejected(db) -> None:
    import psycopg

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        query(
            db,
            "CALL billing.sp_change_plan(%s, %s, %s)",
            (TENANT[1], "10000000-0000-0000-0000-0000000000ff", "2026-03-01"),
        )


@pytest.mark.xfail(
    reason="QA-BILL-11: a back-dated plan change (effective before an existing future-dated "
    "subscription) leaves two open-ended subscriptions (plans.sql sp_change_plan only closes "
    "rows with starts_on < effective_on)",
    strict=True,
)
def test_change_plan_backdated_leaves_single_open_subscription(db) -> None:
    query(db, "CALL billing.sp_change_plan(%s, %s, %s)", (TENANT[3], SCALE, "2026-07-01"))
    query(db, "CALL billing.sp_change_plan(%s, %s, %s)", (TENANT[3], STARTER, "2026-04-01"))
    open_rows = query(
        db,
        "SELECT id FROM billing.subscriptions WHERE tenant_id = %s AND ends_on IS NULL",
        (TENANT[3],),
    )
    assert len(open_rows) == 1


# --- rating ------------------------------------------------------------------


def test_rating_without_history_has_no_rollover(db) -> None:
    row = rating(db, TENANT[7])
    assert row["rollover_units"] == 0


def test_rating_rollover_absorbs_usage(db) -> None:
    row = rating(db, TENANT[1])
    assert 0 < row["rollover_units"] <= 2 * row["quota_units"]
    assert row["billable_units"] == max(
        row["used_units"] - row["rollover_units"] - row["quota_units"], 0
    )


def test_rating_first_tier_boundary(db) -> None:
    row = rating(db, TENANT[6])
    assert (row["used_units"], row["billable_units"]) == (201, 101)
    assert (row["first_tier_units"], row["second_tier_units"]) == (101, 0)
    assert row["overage_amount"] == Decimal("5.56")


def test_rating_second_tier_charges_premium(db) -> None:
    row = rating(db, TENANT[8])
    assert (row["first_tier_units"], row["second_tier_units"]) == (101, 1)
    assert row["overage_amount"] == round(
        Decimal(101) * Decimal("0.055") + Decimal(1) * Decimal("0.055") * Decimal("1.5"), 2
    )


def test_rating_tiers_sum_to_billable_for_active_tenants(db) -> None:
    for n in (1, 3, 5, 6, 7, 8):
        row = rating(db, TENANT[n])
        assert row["first_tier_units"] + row["second_tier_units"] == row["billable_units"], n


@pytest.mark.xfail(
    reason="QA-BILL-06: suspension proration scales billable_units/overage but not the "
    "first/second tier unit split (rating.sql fn_usage_rating)",
    strict=True,
)
def test_rating_tiers_sum_to_billable_for_suspended_tenant(db) -> None:
    row = rating(db, TENANT[2])
    assert row["first_tier_units"] + row["second_tier_units"] == row["billable_units"]


def test_usage_summary_groups_by_kind(db) -> None:
    rows = query(db, "SELECT * FROM billing.fn_usage_summary(%s, %s, %s)", (TENANT[4], *PERIOD))
    assert rows
    total = sum(row[next(k for k in row if "unit" in k)] for row in rows)
    assert total == rating(db, TENANT[4])["used_units"]


def test_finalize_rating_is_idempotent(db) -> None:
    for _ in range(2):
        query(db, "CALL billing.sp_finalize_rating(%s, %s, %s)", (TENANT[1], *PERIOD))
    periods = query(
        db,
        "SELECT id FROM billing.rating_periods WHERE tenant_id = %s AND period_start = %s",
        (TENANT[1], PERIOD[0]),
    )
    assert len(periods) == 1


# --- invoicing -----------------------------------------------------------------


def test_preview_line_layout(db) -> None:
    lines = preview(db, TENANT[6])
    assert [line["line_type"] for line in lines] == ["plan", "usage", "tax", "tax", "credit"]
    assert lines[0]["amount"] == Decimal("49.00")
    assert lines[1]["amount"] == rating(db, TENANT[6])["overage_amount"]


def test_preview_tax_exempt_tenant_has_zero_tax(db) -> None:
    make_tenant(db, STARTER, tax_exempt=True)
    taxes = [line["amount"] for line in preview(db, QA_TENANT) if line["line_type"] == "tax"]
    assert taxes and all(amount == 0 for amount in taxes)


@pytest.mark.xfail(
    reason="QA-BILL-04: preview tax lines are not rounded to cents (e.g. 2.2506000000000000)",
    strict=True,
)
def test_preview_amounts_are_cents(db) -> None:
    for line in preview(db, TENANT[6]):
        assert line["amount"] == round(line["amount"], 2), line


@pytest.mark.xfail(
    reason="QA-BILL-05: preview for a tenant with no subscription returns null plan/tax lines "
    "instead of an empty result or an error",
    strict=True,
)
def test_preview_unknown_tenant_has_no_null_lines(db) -> None:
    lines = preview(db, "00000000-0000-0000-0000-0000000000ff")
    assert all(line["amount"] is not None for line in lines)


def test_issue_invoice_persists_totals(db) -> None:
    query(db, "CALL billing.sp_issue_invoice(%s, %s, %s)", (TENANT[6], *PERIOD))
    invoice = query(
        db,
        "SELECT i.* FROM billing.invoices i JOIN billing.rating_periods p "
        "ON p.id = i.period_id WHERE i.tenant_id = %s AND p.period_start = %s",
        (TENANT[6], PERIOD[0]),
    )[0]
    assert invoice["subtotal"] == Decimal("54.56")
    assert invoice["status"] == "issued"
    assert invoice["total"] == invoice["subtotal"] + invoice["tax"]
    lines = query(db, "SELECT * FROM billing.fn_invoice_lines(%s)", (invoice["id"],))
    assert [line["line_type"] for line in lines][:2] == ["plan", "usage"]
    assert sum(line["amount"] for line in lines) == invoice["total"]


def test_issue_invoice_consumes_credit_and_never_goes_negative(db) -> None:
    before = query(
        db,
        "SELECT COALESCE(sum(remaining_amount), 0) AS r FROM billing.credit_notes "
        "WHERE tenant_id = %s",
        (TENANT[4],),
    )[0]["r"]
    query(db, "CALL billing.sp_issue_invoice(%s, %s, %s)", (TENANT[4], *PERIOD))
    after = query(
        db,
        "SELECT COALESCE(sum(remaining_amount), 0) AS r FROM billing.credit_notes "
        "WHERE tenant_id = %s",
        (TENANT[4],),
    )[0]["r"]
    totals = query(db, "SELECT total FROM billing.invoices WHERE tenant_id = %s", (TENANT[4],))
    assert after < before
    assert all(row["total"] >= 0 for row in totals)


@pytest.mark.xfail(
    reason="QA-BILL-04: tax is split into two halves rounded separately; GROWTH with no usage "
    "issues tax 12.30 instead of round(149 * 0.0825, 2) = 12.29 (seeded invoices use 12.29)",
    strict=True,
)
def test_issue_invoice_tax_rounds_once(db) -> None:
    make_tenant(db, GROWTH)
    query(db, "CALL billing.sp_issue_invoice(%s, %s, %s)", (QA_TENANT, *PERIOD))
    invoice = query(
        db, "SELECT subtotal, tax FROM billing.invoices WHERE tenant_id = %s", (QA_TENANT,)
    )[0]
    assert invoice["tax"] == round(invoice["subtotal"] * Decimal("0.0825"), 2)


# --- dunning -----------------------------------------------------------------


def test_overdue_accounts_lists_seeded_invoices(db) -> None:
    rows = query(db, "SELECT * FROM billing.fn_overdue_accounts(%s)", ("2026-02-28",))
    assert [row["days_overdue"] for row in rows] == [27, 15]
    assert {str(row["tenant_id"]) for row in rows} == {TENANT[2], TENANT[5]}


def test_overdue_accounts_excludes_future_as_of(db) -> None:
    assert query(db, "SELECT * FROM billing.fn_overdue_accounts(%s)", ("2026-01-01",)) == []


def test_schedule_dunning_moves_weekend_to_monday(db) -> None:
    query(db, "CALL billing.sp_schedule_dunning(%s)", ("2026-02-14",))  # Saturday
    rows = query(
        db,
        "SELECT scheduled_for FROM billing.dunning_attempts "
        "WHERE scheduled_for >= '2026-02-14' AND status = 'scheduled'",
    )
    assert rows and all(row["scheduled_for"] == date(2026, 2, 16) for row in rows)


def test_suspend_overdue_suspends_and_notifies_once(db) -> None:
    for _ in range(2):
        query(db, "CALL billing.sp_suspend_overdue(%s)", ("2026-02-28",))
    tenant = query(db, "SELECT status FROM billing.tenants WHERE id = %s", (TENANT[5],))[0]
    notes = query(
        db,
        "SELECT id FROM billing.notifications WHERE tenant_id = %s "
        "AND kind = 'suspension' AND sent_at = '2026-02-28'",
        (TENANT[5],),
    )
    assert tenant["status"] == "suspended"
    assert len(notes) == 1


def test_suspend_overdue_respects_14_day_grace(db) -> None:
    query(db, "CALL billing.sp_suspend_overdue(%s)", ("2026-02-26",))
    tenant = query(db, "SELECT status FROM billing.tenants WHERE id = %s", (TENANT[5],))[0]
    assert tenant["status"] == "active"
