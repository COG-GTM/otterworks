from decimal import Decimal

import pytest

pytestmark = pytest.mark.db

T1 = "00000000-0000-0000-0000-000000000001"
T2 = "00000000-0000-0000-0000-000000000002"
T3 = "00000000-0000-0000-0000-000000000003"
T4 = "00000000-0000-0000-0000-000000000004"
T5 = "00000000-0000-0000-0000-000000000005"
T7 = "00000000-0000-0000-0000-000000000007"
T9 = "00000000-0000-0000-0000-000000000009"
GROWTH = "10000000-0000-0000-0000-000000000002"
SCALE = "10000000-0000-0000-0000-000000000003"
INV1 = "60000000-0000-0000-0000-000000000001"
INV2 = "60000000-0000-0000-0000-000000000002"
FEB = {"period_start": "2026-02-01", "period_end": "2026-02-28"}


def invoice_row(db, tenant):
    return db(
        "SELECT status, subtotal::text, tax::text, total::text FROM billing.invoices "
        "WHERE period_id = md5(%s || '2026-02-01')::uuid",
        (tenant,),
    )


def credits(db, tenant):
    return [r[0] for r in db(
        "SELECT remaining_amount::text FROM billing.credit_notes WHERE tenant_id = %s ORDER BY issued_on, id",
        (tenant,),
    )]


def test_health_and_index(client, db):
    assert client.get("/health").get_json()["status"] == "UP"
    page = client.get("/").get_data(as_text=True)
    for code in ("STARTER", "GROWTH", "SCALE"):
        assert code in page


def test_plans_catalog_order(client, db):
    plans = client.get("/plans").get_json()
    assert [p["code"] for p in plans] == ["STARTER", "GROWTH", "SCALE"]
    assert [p["monthly_fee"] for p in plans] == ["49.00", "149.00", "499.00"]
    assert plans[0]["plan_id"] == "10000000-0000-0000-0000-000000000001"


def test_inactive_plans_hidden(client, db):
    db("UPDATE billing.plans SET active = false WHERE code = 'GROWTH'")
    assert [p["code"] for p in client.get("/plans").get_json()] == ["STARTER", "SCALE"]


def test_entitlement(client, db):
    [row] = client.get(f"/plans/{T1}/entitlement").get_json()
    assert row["plan_code"] == "STARTER"
    assert row["included_units"] == 100
    assert row["subscription_status"] == "active"
    [row] = client.get(f"/plans/{T2}/entitlement?on=2026-02-28").get_json()
    assert (row["plan_code"], row["subscription_status"]) == ("GROWTH", "suspended")


def test_entitlement_before_subscription_and_unknown_tenant(client, db):
    assert client.get(f"/plans/{T1}/entitlement?on=2025-12-31").get_json() == []
    assert client.get("/plans/00000000-0000-0000-0000-0000000000ff/entitlement").get_json() == []


def test_change_plan_round_trip(client, db):
    response = client.post(
        f"/plans/{T1}/change", data={"plan_id": GROWTH, "effective_on": "2026-03-01"},
        follow_redirects=True,
    )
    [row] = response.get_json()
    assert row["plan_code"] == "GROWTH"
    assert db(
        "SELECT plan_id::text, starts_on::text, ends_on::text, status FROM billing.subscriptions "
        "WHERE tenant_id = %s ORDER BY starts_on", (T1,),
    ) == [
        ("10000000-0000-0000-0000-000000000001", "2026-01-01", "2026-02-28", "active"),
        (GROWTH, "2026-03-01", None, "active"),
    ]
    [row] = client.get(f"/plans/{T1}/entitlement?on=2026-02-28").get_json()
    assert row["plan_code"] == "STARTER"


def test_change_plan_twice_same_day_conflicts(client, db):
    form = {"plan_id": SCALE, "effective_on": "2026-03-15"}
    assert client.post(f"/plans/{T4}/change", data=form).status_code == 302
    with pytest.raises(Exception, match="duplicate key"):
        client.post(f"/plans/{T4}/change", data=form)


@pytest.mark.xfail(strict=True, reason="sp_change_plan resets a suspended subscription to 'active' when closing it")
def test_change_plan_keeps_suspended_history(client, db):
    client.post(f"/plans/{T2}/change", data={"plan_id": SCALE, "effective_on": "2026-03-01"})
    [(status,)] = db(
        "SELECT status FROM billing.subscriptions WHERE tenant_id = %s AND starts_on = '2026-01-01'", (T2,)
    )
    assert status == "suspended"


def test_change_plan_bad_uuid_errors(client, db):
    with pytest.raises(Exception, match="uuid"):
        client.post(f"/plans/not-a-uuid/change", data={"plan_id": GROWTH, "effective_on": "2026-03-01"})


def test_rating_preview_without_prior_periods(client, db):
    [row] = client.post("/api/rating/preview", json={"tenant_id": T7, **FEB}).get_json()
    assert (row["used_units"], row["quota_units"], row["rollover_units"], row["billable_units"]) == (260, 100, 0, 160)
    assert row["period_start"] == "2026-02-01"


def test_rating_preview_rollover_is_capped(client, db):
    [row] = client.post("/api/rating/preview", json={"tenant_id": T1, **FEB}).get_json()
    assert row["rollover_units"] == 200
    assert (row["billable_units"], row["overage_amount"]) == (0, "0.00")


def test_rating_preview_under_quota(client, db):
    [row] = client.post("/api/rating/preview", json={"tenant_id": T4, **FEB}).get_json()
    assert (row["used_units"], row["billable_units"], row["overage_amount"]) == (50, 0, "0.00")


@pytest.mark.xfail(strict=True, reason="suspension proration bills the days after suspended_on, not the active days")
def test_rating_suspension_proration_bills_active_days(client, db):
    def amount(suspended_on):
        db("UPDATE billing.subscriptions SET suspended_on = %s WHERE tenant_id = %s", (suspended_on, T2))
        [row] = client.post("/api/rating/preview", json={"tenant_id": T2, **FEB}).get_json()
        return row["billable_units"]

    assert amount("2026-02-22") > amount("2026-02-08")


def test_rating_finalize_persists_period(client, db):
    assert client.post("/api/rating/finalize", json={"tenant_id": T7, **FEB}).get_json() == {"status": "finalized"}
    assert db(
        "SELECT rp.period_end::text, rr.used_units, rr.rollover_units, rr.billable_units "
        "FROM billing.rating_periods rp JOIN billing.rating_results rr ON rr.period_id = rp.id "
        "WHERE rp.tenant_id = %s", (T7,),
    ) == [("2026-02-28", 260, 0, 160)]
    client.post("/api/rating/finalize", json={"tenant_id": T7, "period_start": "2026-02-01", "period_end": "2026-02-27"})
    assert db("SELECT count(*), max(period_end)::text FROM billing.rating_periods WHERE tenant_id = %s", (T7,)) == [
        (1, "2026-02-27")
    ]


def test_finalized_rollover_feeds_next_period(client, db):
    client.post("/api/rating/finalize", json={"tenant_id": T4, **FEB})
    [row] = client.post(
        "/api/rating/preview", json={"tenant_id": T4, "period_start": "2026-03-01", "period_end": "2026-03-31"}
    ).get_json()
    assert row["rollover_units"] == 50
    assert row["used_units"] == 0


def test_usage_summary(db):
    assert db("SELECT * FROM billing.fn_usage_summary(%s, '2026-02-01', '2026-02-28')", (T4,)) == [
        ("api", 1, 20), ("storage", 1, 30),
    ]
    assert db("SELECT * FROM billing.fn_usage_summary(%s, '2026-03-01', '2026-03-31')", (T4,)) == []


def test_invoice_preview_lines(client, db):
    lines = client.get(f"/api/invoices/{T4}/preview").get_json()
    assert [(l["line_no"], l["line_type"]) for l in lines] == [
        (1, "plan"), (2, "usage"), (3, "tax"), (4, "tax"), (5, "credit"),
    ]
    assert lines[0]["amount"] == "49.00"
    assert lines[4]["credit_applied"] == "53.04"
    assert lines[4]["total"] == "-53.04"


def test_invoice_preview_tax_exempt(client, db):
    lines = client.get(f"/api/invoices/{T3}/preview?period_start=2026-02-01&period_end=2026-02-28").get_json()
    assert [Decimal(l["amount"]) for l in lines if l["line_type"] == "tax"] == [0, 0]


@pytest.mark.xfail(strict=True, reason="json_value uses str(Decimal): exempt tax renders as '0E-20' and taxable lines as unrounded '2.0212500000000000'")
def test_invoice_preview_amounts_are_plain_cents(client, db):
    for tenant in (T3, T4):
        for line in client.get(f"/api/invoices/{tenant}/preview").get_json():
            assert line["amount"] == f"{Decimal(line['amount']):.2f}"


def test_issue_invoice_applies_credits_in_issue_order(client, db):
    response = client.post(f"/api/invoices/{T9}/issue", data=FEB)
    assert response.get_json() == {"status": "issued"}
    assert invoice_row(db, T9) == [("issued", "49.00", "4.04", "0.00")]
    assert credits(db, T9) == ["0.00", "6.96"]


def test_issue_invoice_equal_dates_ordered_by_id(client, db):
    client.post(f"/api/invoices/{T4}/issue", data=FEB)
    assert credits(db, T4) == ["0.00", "6.96"]
    [(invoice_id,)] = db("SELECT id::text FROM billing.invoices WHERE tenant_id = %s", (T4,))
    lines = client.get(f"/api/invoices/{invoice_id}/lines").get_json()
    assert [(l["line_type"], l["amount"]) for l in lines] == [
        ("plan", "49.00"), ("usage", "0.00"), ("tax", "2.02"), ("tax", "2.02"), ("credit", "-53.04"),
    ]


def test_issue_invoice_without_credits(client, db):
    client.post(f"/api/invoices/{T7}/issue", data=FEB)
    [(status, subtotal, tax, total)] = invoice_row(db, T7)
    assert status == "issued"
    assert float(total) == pytest.approx(float(subtotal) + float(tax))


@pytest.mark.xfail(strict=True, reason="re-issuing the same period consumes credit notes again and changes the invoice total")
def test_reissue_invoice_is_idempotent(client, db):
    client.post(f"/api/invoices/{T9}/issue", data=FEB)
    first = (invoice_row(db, T9), credits(db, T9))
    client.post(f"/api/invoices/{T9}/issue", data=FEB)
    assert (invoice_row(db, T9), credits(db, T9)) == first


def test_invoice_lines_seeded_and_unknown(client, db):
    assert [(l["line_type"], l["amount"]) for l in client.get(f"/api/invoices/{INV1}/lines").get_json()] == [
        ("plan", "149.00"), ("usage", "12.29"),
    ]
    assert client.get("/api/invoices/60000000-0000-0000-0000-0000000000ff/lines").get_json() == []


def test_overdue_accounts(client, db):
    rows = client.get("/api/dunning/overdue").get_json()
    assert [(r["tenant_id"], r["days_overdue"], r["tenant_status"]) for r in rows] == [
        (T2, 27, "suspended"), (T5, 15, "active"),
    ]
    assert rows[0]["total"] == "161.29"
    assert client.get("/api/dunning/overdue?as_of=2026-02-01").get_json() == []


def attempts(db):
    return db(
        "SELECT invoice_id::text, attempt_no, scheduled_for::text FROM billing.dunning_attempts "
        "ORDER BY invoice_id, attempt_no"
    )


@pytest.mark.parametrize("as_of,expected", [
    ("2026-02-14", "2026-02-16"),
    ("2026-02-15", "2026-02-16"),
    ("2026-02-17", "2026-02-17"),
])
def test_schedule_dunning_shifts_weekends(client, db, as_of, expected):
    assert client.post("/api/dunning/schedule", data={"as_of": as_of}).get_json() == {"status": "scheduled"}
    assert attempts(db) == [
        (INV1, 1, expected),
        (INV2, 1, "2026-02-16"),
        (INV2, 2, expected),
    ]


def test_schedule_dunning_skips_non_overdue(client, db):
    db("UPDATE billing.invoices SET status = 'paid' WHERE status = 'overdue'")
    client.post("/api/dunning/schedule", data={"as_of": "2026-02-17"})
    assert attempts(db) == [(INV2, 1, "2026-02-16")]


def test_suspend_overdue(client, db):
    assert client.post("/api/dunning/suspend", data={"as_of": "2026-02-28"}).get_json() == {"status": "suspended"}
    assert db("SELECT status FROM billing.tenants WHERE id = %s", (T5,)) == [("suspended",)]
    assert db("SELECT status, suspended_on::text FROM billing.subscriptions WHERE tenant_id = %s", (T5,)) == [
        ("suspended", "2026-02-28"),
    ]
    client.post("/api/dunning/suspend", data={"as_of": "2026-02-28"})
    assert db("SELECT tenant_id::text FROM billing.notifications WHERE kind = 'suspension'") == [(T5,)]


def test_suspend_overdue_grace_period(client, db):
    client.post("/api/dunning/suspend", data={"as_of": "2026-02-26"})
    assert db("SELECT status FROM billing.tenants WHERE id = %s", (T5,)) == [("active",)]
    assert db("SELECT count(*) FROM billing.notifications WHERE kind = 'suspension'") == [(0,)]
    client.post("/api/dunning/suspend", data={"as_of": "2026-02-27"})
    assert db("SELECT status FROM billing.tenants WHERE id = %s", (T5,)) == [("suspended",)]
