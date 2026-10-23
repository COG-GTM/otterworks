"""Unit tests for the legacy Flask facade with the database layer stubbed."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

import app as legacy

TENANT = "00000000-0000-0000-0000-000000000001"
GROWTH = "10000000-0000-0000-0000-000000000002"


@pytest.fixture
def calls(monkeypatch):
    recorded: dict = {"select": [], "execute": [], "result": []}

    def fake_select(sql, params=()):
        recorded["select"].append((sql, params))
        return recorded["result"]

    def fake_execute(sql, params=()):
        recorded["execute"].append((sql, params))

    monkeypatch.setattr(legacy, "select", fake_select)
    monkeypatch.setattr(legacy, "execute", fake_execute)
    return recorded


@pytest.fixture
def client():
    legacy.app.config["TESTING"] = True
    return legacy.app.test_client()


def test_json_value_stringifies_decimal_date_uuid() -> None:
    assert legacy.json_value(Decimal("49.00")) == "49.00"
    assert legacy.json_value(date(2026, 2, 28)) == "2026-02-28"
    assert legacy.json_value(uuid.UUID(TENANT)) == TENANT
    assert legacy.json_value(7) == 7
    assert legacy.json_value(None) is None


def test_health_reports_up(client, calls) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "UP", "service": "legacy-billing"}
    assert calls["select"] == [("SELECT 1", ())]


def test_index_renders_plan_list(client, calls) -> None:
    calls["result"] = [{"code": "STARTER", "monthly_fee": "49.00", "included_units": 100}]
    response = client.get("/")
    assert response.status_code == 200
    assert "STARTER" in response.get_data(as_text=True)
    assert "100 units" in response.get_data(as_text=True)


def test_plans_calls_catalog_function(client, calls) -> None:
    calls["result"] = [{"code": "STARTER"}]
    assert client.get("/plans").get_json() == [{"code": "STARTER"}]
    assert calls["select"][0][0] == "SELECT * FROM billing.fn_list_plans()"


def test_entitlement_defaults_as_of_date(client, calls) -> None:
    client.get(f"/plans/{TENANT}/entitlement")
    assert calls["select"][0][1] == (TENANT, "2026-02-28")


def test_entitlement_passes_on_query(client, calls) -> None:
    client.get(f"/plans/{TENANT}/entitlement?on=2026-03-15")
    assert calls["select"][0][1] == (TENANT, "2026-03-15")


def test_change_plan_calls_procedure_and_redirects(client, calls) -> None:
    response = client.post(
        f"/plans/{TENANT}/change", data={"plan_id": GROWTH, "effective_on": "2026-03-01"}
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/plans/{TENANT}/entitlement?on=2026-03-01")
    assert calls["execute"] == [
        ("CALL billing.sp_change_plan(%s, %s, %s)", (TENANT, GROWTH, "2026-03-01"))
    ]


@pytest.mark.parametrize("missing", ["plan_id", "effective_on"])
def test_change_plan_requires_form_fields(client, calls, missing) -> None:
    data = {"plan_id": GROWTH, "effective_on": "2026-03-01"}
    data.pop(missing)
    assert client.post(f"/plans/{TENANT}/change", data=data).status_code == 400
    assert calls["execute"] == []


def test_rating_preview_reads_json_body(client, calls) -> None:
    body = {"tenant_id": TENANT, "period_start": "2026-02-01", "period_end": "2026-02-28"}
    client.post("/api/rating/preview", json=body)
    assert calls["select"][0] == (
        "SELECT * FROM billing.fn_usage_rating(%s, %s, %s)",
        (TENANT, "2026-02-01", "2026-02-28"),
    )


def test_rating_finalize_returns_status(client, calls) -> None:
    body = {"tenant_id": TENANT, "period_start": "2026-02-01", "period_end": "2026-02-28"}
    response = client.post("/api/rating/finalize", json=body)
    assert response.get_json() == {"status": "finalized"}
    assert calls["execute"][0][0] == "CALL billing.sp_finalize_rating(%s, %s, %s)"


def test_invoice_preview_defaults_period(client, calls) -> None:
    client.get(f"/api/invoices/{TENANT}/preview")
    assert calls["select"][0][1] == (TENANT, "2026-02-01", "2026-02-28")


def test_invoice_issue_calls_procedure(client, calls) -> None:
    response = client.post(
        f"/api/invoices/{TENANT}/issue",
        data={"period_start": "2026-02-01", "period_end": "2026-02-28"},
    )
    assert response.get_json() == {"status": "issued"}
    assert calls["execute"][0][1] == (TENANT, "2026-02-01", "2026-02-28")


def test_invoice_issue_requires_period(client, calls) -> None:
    response = client.post(f"/api/invoices/{TENANT}/issue", data={"period_start": "2026-02-01"})
    assert response.status_code == 400
    assert calls["execute"] == []


def test_invoice_lines_by_invoice(client, calls) -> None:
    invoice = "60000000-0000-0000-0000-000000000001"
    client.get(f"/api/invoices/{invoice}/lines")
    assert calls["select"][0] == ("SELECT * FROM billing.fn_invoice_lines(%s)", (invoice,))


def test_overdue_defaults_as_of(client, calls) -> None:
    client.get("/api/dunning/overdue")
    assert calls["select"][0][1] == ("2026-02-28",)


@pytest.mark.parametrize(
    ("path", "proc", "status"),
    [
        ("/api/dunning/schedule", "sp_schedule_dunning", "scheduled"),
        ("/api/dunning/suspend", "sp_suspend_overdue", "suspended"),
    ],
)
def test_dunning_commands(client, calls, path, proc, status) -> None:
    response = client.post(path, data={"as_of": "2026-02-28"})
    assert response.get_json() == {"status": status}
    assert calls["execute"] == [(f"CALL billing.{proc}(%s)", ("2026-02-28",))]


@pytest.mark.parametrize("path", ["/api/dunning/schedule", "/api/dunning/suspend"])
def test_dunning_commands_require_as_of(client, calls, path) -> None:
    assert client.post(path, data={}).status_code == 400


@pytest.mark.xfail(
    reason="QA-BILL-02: malformed tenant UUID surfaces as HTTP 500 (no input validation)",
    strict=True,
)
def test_entitlement_malformed_uuid_is_client_error(client, monkeypatch) -> None:
    def invalid(*_args, **_kwargs):
        raise psycopg.errors.InvalidTextRepresentation("invalid input syntax for type uuid")

    monkeypatch.setattr(legacy, "select", invalid)
    legacy.app.config["TESTING"] = False
    try:
        response = client.get("/plans/not-a-uuid/entitlement")
    finally:
        legacy.app.config["TESTING"] = True
    assert response.status_code == 400


@pytest.mark.xfail(
    reason="QA-BILL-02: missing JSON keys in /api/rating/preview raise KeyError -> HTTP 500",
    strict=True,
)
def test_rating_preview_missing_field_is_client_error(client, calls) -> None:
    legacy.app.config["TESTING"] = False
    try:
        response = client.post("/api/rating/preview", json={"tenant_id": TENANT})
    finally:
        legacy.app.config["TESTING"] = True
    assert response.status_code == 400


@pytest.mark.xfail(
    reason="QA-BILL-03: unknown tenant entitlement returns 200 [] (billing-service returns 404)",
    strict=True,
)
def test_entitlement_unknown_tenant_is_404(client, calls) -> None:
    calls["result"] = []
    response = client.get("/plans/00000000-0000-0000-0000-0000000000ff/entitlement")
    assert response.status_code == 404


@pytest.mark.xfail(
    reason="QA-BILL-12: gunicorn runs a single sync worker (Dockerfile CMD), so one idle "
    "keep-alive browser connection blocks every request until the 30s WORKER TIMEOUT",
    strict=True,
)
def test_gunicorn_serves_concurrent_connections() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    cmd = next(line for line in dockerfile.splitlines() if line.startswith("CMD"))
    assert any(flag in cmd for flag in ("--workers", "-w", "--threads", "gthread", "gevent"))
