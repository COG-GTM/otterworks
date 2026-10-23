"""QA functional tests: legacy-billing JSON API and billing-service parity."""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from qa_billing_support import (
    BILLING_SERVICE_URL,
    GROWTH,
    LEGACY_BILLING_URL,
    SCALE,
    STARTER,
    TENANT,
    UNKNOWN_TENANT,
    service_client,
)

pytestmark = pytest.mark.api_flow
PERIOD = {"period_start": "2026-02-01", "period_end": "2026-02-28"}


@pytest.fixture(scope="module")
def legacy():
    client = service_client(LEGACY_BILLING_URL)
    yield client
    client.close()


@pytest.fixture(scope="module")
def target():
    client = service_client(BILLING_SERVICE_URL)
    yield client
    client.close()


@pytest.fixture
def seeded_target(target):
    response = target.post("/internal/reset")
    if response.status_code == 404:
        pytest.skip("billing-service internal reset disabled")
    assert response.status_code == 204, response.text
    return target


def unique_future_date() -> str:
    # Strictly increasing across runs (one day per wall-clock minute): legacy sp_change_plan
    # leaves overlapping open subscriptions for back-dated changes (QA-BILL-11).
    return (date(2030, 1, 1) + timedelta(days=int(time.time() // 60) - 29_800_000)).isoformat()


# --- legacy plans module -------------------------------------------------------


def test_legacy_plan_catalog(legacy):
    plans = legacy.get("/plans").json()
    assert [plan["code"] for plan in plans] == ["STARTER", "GROWTH", "SCALE"]
    assert [plan["monthly_fee"] for plan in plans] == ["49.00", "149.00", "499.00"]


def test_legacy_server_rendered_index_matches_json(legacy):
    html = legacy.get("/").text
    for plan in legacy.get("/plans").json():
        assert f"{plan['code']} — {plan['monthly_fee']} / {plan['included_units']} units" in html


def test_legacy_entitlement_default_date(legacy):
    rows = legacy.get(f"/plans/{TENANT[1]}/entitlement").json()
    assert rows[0]["plan_code"] == "STARTER"
    assert rows[0]["subscription_status"] == "active"


def test_legacy_change_plan_redirects_to_entitlement(legacy):
    effective = unique_future_date()
    response = legacy.post(
        f"/plans/{TENANT[7]}/change", data={"plan_id": SCALE, "effective_on": effective}
    )
    assert response.status_code == 302
    assert f"/plans/{TENANT[7]}/entitlement?on={effective}" in response.headers["location"]
    rows = legacy.get(f"/plans/{TENANT[7]}/entitlement", params={"on": effective}).json()
    assert rows[0]["plan_code"] == "SCALE"


def test_legacy_change_plan_missing_field_is_400(legacy):
    response = legacy.post(f"/plans/{TENANT[7]}/change", data={"plan_id": GROWTH})
    assert response.status_code == 400


@pytest.mark.xfail(reason="QA-BILL-02: malformed tenant UUID returns HTTP 500", strict=True)
def test_legacy_malformed_tenant_is_client_error(legacy):
    assert legacy.get("/plans/not-a-uuid/entitlement").status_code == 400


# --- legacy rating / invoicing / dunning -------------------------------------------


def test_legacy_rating_preview_boundary(legacy):
    row = legacy.post("/api/rating/preview", json={"tenant_id": TENANT[6], **PERIOD}).json()[0]
    assert (row["billable_units"], row["first_tier_units"], row["second_tier_units"]) == (
        101,
        101,
        0,
    )
    assert row["overage_amount"] == "5.56"


@pytest.mark.xfail(
    reason="QA-BILL-06: suspended tenant tiers (101+99) do not sum to prorated billable (100)",
    strict=True,
)
def test_legacy_rating_suspended_tiers_consistent(legacy):
    row = legacy.post("/api/rating/preview", json={"tenant_id": TENANT[2], **PERIOD}).json()[0]
    assert row["first_tier_units"] + row["second_tier_units"] == row["billable_units"]


def test_legacy_invoice_preview_then_issue(legacy):
    preview = legacy.get(f"/api/invoices/{TENANT[6]}/preview", params=PERIOD).json()
    assert [line["line_type"] for line in preview] == ["plan", "usage", "tax", "tax", "credit"]
    response = legacy.post(f"/api/invoices/{TENANT[6]}/issue", data=PERIOD)
    assert response.json() == {"status": "issued"}


def test_legacy_invoice_lines_for_seeded_invoice(legacy):
    lines = legacy.get("/api/invoices/60000000-0000-0000-0000-000000000001/lines").json()
    assert lines
    assert {line["line_type"] for line in lines} <= {"plan", "usage", "tax", "credit"}


@pytest.mark.xfail(
    reason="QA-BILL-04: preview tax lines are unrounded (e.g. 2.2506000000000000)", strict=True
)
def test_legacy_invoice_preview_amounts_are_cents(legacy):
    for line in legacy.get(f"/api/invoices/{TENANT[6]}/preview", params=PERIOD).json():
        assert Decimal(line["amount"]) == round(Decimal(line["amount"]), 2), line


@pytest.mark.xfail(
    reason="QA-BILL-05: preview for an unknown tenant returns 200 with null amounts",
    strict=True,
)
def test_legacy_invoice_preview_unknown_tenant(legacy):
    response = legacy.get(f"/api/invoices/{UNKNOWN_TENANT}/preview", params=PERIOD)
    assert response.status_code == 404 or response.json() == []


def test_legacy_invoice_issue_requires_period(legacy):
    response = legacy.post(f"/api/invoices/{TENANT[6]}/issue", data={"period_start": "2026-02-01"})
    assert response.status_code == 400


def test_legacy_dunning_overdue(legacy):
    rows = legacy.get("/api/dunning/overdue", params={"as_of": "2026-02-28"}).json()
    assert {row["tenant_id"] for row in rows} <= {TENANT[2], TENANT[5]}
    assert all(row["days_overdue"] > 0 for row in rows)


def test_legacy_dunning_requires_as_of(legacy):
    assert legacy.post("/api/dunning/schedule", data={}).status_code == 400
    assert legacy.post("/api/dunning/suspend", data={}).status_code == 400


# --- billing-service (target) and parity -----------------------------------------


def test_target_catalog_matches_legacy(legacy, seeded_target):
    legacy_plans = legacy.get("/plans").json()
    target_plans = seeded_target.get("/api/plans").json()
    assert [(p["code"], p["monthly_fee"]) for p in target_plans] == [
        (p["code"], p["monthly_fee"]) for p in legacy_plans
    ]
    assert [p["plan_id"] for p in target_plans] == [STARTER, GROWTH, SCALE]


@pytest.mark.parametrize("tenant", [TENANT[1], TENANT[2], TENANT[3]])
def test_target_entitlement_matches_legacy(legacy, seeded_target, tenant):
    old = legacy.get(f"/plans/{tenant}/entitlement", params={"on": "2026-02-28"}).json()[0]
    new = seeded_target.get(f"/api/tenants/{tenant}/entitlement", params={"on": "2026-02-28"})
    assert new.status_code == 200, new.text
    body = new.json()
    for field in ("plan_code", "tier", "included_units", "subscription_status"):
        assert body[field] == old[field], field


def test_target_plan_change_flow(seeded_target):
    url = f"/api/tenants/{TENANT[1]}/plan-change"
    payload = {"plan_id": GROWTH, "effective_on": "2026-03-01"}
    first = seeded_target.post(url, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["latest_plan"] == GROWTH
    closed = [s for s in first.json()["subscriptions"] if s["ends_on"] == "2026-02-28"]
    assert closed
    duplicate = seeded_target.post(url, json=payload)
    assert duplicate.status_code == 409
    after = seeded_target.get(
        f"/api/tenants/{TENANT[1]}/entitlement", params={"on": "2026-03-01"}
    ).json()
    assert after["plan_code"] == "GROWTH"


def test_target_plan_change_unknown_plan_is_400(seeded_target):
    response = seeded_target.post(
        f"/api/tenants/{TENANT[1]}/plan-change",
        json={"plan_id": "10000000-0000-0000-0000-0000000000ff", "effective_on": "2026-03-01"},
    )
    assert response.status_code == 400


def test_target_validation_errors(seeded_target):
    assert seeded_target.get("/api/tenants/not-a-uuid/entitlement?on=2026-02-28").status_code == 422
    assert seeded_target.get(f"/api/tenants/{TENANT[1]}/entitlement").status_code == 422
    bad = seeded_target.post(f"/api/tenants/{TENANT[1]}/plan-change", json={"plan_id": "x"})
    assert bad.status_code == 422


def test_target_unknown_tenant_is_404(seeded_target):
    response = seeded_target.get(
        f"/api/tenants/{UNKNOWN_TENANT}/entitlement", params={"on": "2026-02-28"}
    )
    assert response.status_code == 404


@pytest.mark.xfail(
    reason="QA-BILL-03: legacy returns 200 [] for an unknown tenant; billing-service returns 404",
    strict=True,
)
def test_unknown_tenant_contract_parity(legacy, seeded_target):
    old = legacy.get(f"/plans/{UNKNOWN_TENANT}/entitlement", params={"on": "2026-02-28"})
    new = seeded_target.get(
        f"/api/tenants/{UNKNOWN_TENANT}/entitlement", params={"on": "2026-02-28"}
    )
    assert old.status_code == new.status_code


@pytest.mark.skip(
    reason="QA-BILL-01: needs a fresh billing-service container (empty DB until /internal/reset);"
    " verified manually in docs/qa/billing.md"
)
def test_target_catalog_seeded_on_fresh_boot(target):
    assert target.get("/api/plans").json()
