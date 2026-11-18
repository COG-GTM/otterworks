import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app as billing_app


class FakeCursor:
    def __init__(self, calls, result):
        self.calls = calls
        self.columns, self.data = result
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        self.description = [SimpleNamespace(name=name) for name in self.columns]

    def __iter__(self):
        return iter(self.data)


class FakeConnection:
    def __init__(self, calls, result):
        self.calls = calls
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self.calls, self.result)


@pytest.fixture
def fake_db(monkeypatch):
    state = SimpleNamespace(calls=[], result=([], []))
    monkeypatch.setattr(
        billing_app, "db_connect", lambda: FakeConnection(state.calls, state.result)
    )
    return state


TENANT = "00000000-0000-0000-0000-000000000001"


def test_db_connect_uses_env(monkeypatch):
    captured = {}
    monkeypatch.setattr(billing_app.psycopg, "connect", lambda **kw: captured.update(kw) or "conn")
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert billing_app.db_connect() == "conn"
    assert captured == {
        "host": "localhost", "port": 5432, "dbname": "billing_dev",
        "user": "billing", "password": "billing",
    }
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_NAME", "billing_x")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    billing_app.db_connect()
    assert captured == {"host": "db.internal", "port": 6543, "dbname": "billing_x", "user": "u", "password": "p"}


@pytest.mark.parametrize("value,expected", [
    (Decimal("12.50"), "12.50"),
    (date(2026, 2, 28), "2026-02-28"),
    (uuid.UUID(TENANT), TENANT),
    (7, 7),
    ("text", "text"),
    (None, None),
])
def test_json_value(value, expected):
    assert billing_app.json_value(value) == expected


def test_select_maps_rows_by_column_name(fake_db):
    fake_db.result = (["id", "fee", "on"], [(uuid.UUID(TENANT), Decimal("1.10"), date(2026, 1, 1))])
    assert billing_app.select("SELECT x WHERE a = %s", (1,)) == [
        {"id": TENANT, "fee": "1.10", "on": "2026-01-01"}
    ]
    assert fake_db.calls == [("SELECT x WHERE a = %s", (1,))]


def test_execute_runs_statement(fake_db):
    billing_app.execute("CALL x(%s)", ("a",))
    assert fake_db.calls == [("CALL x(%s)", ("a",))]


def test_health(client, fake_db):
    fake_db.result = (["?column?"], [(1,)])
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "UP", "service": "legacy-billing"}
    assert fake_db.calls == [("SELECT 1", ())]


def test_health_propagates_db_failure(client, monkeypatch):
    def boom():
        raise billing_app.psycopg.OperationalError("down")

    monkeypatch.setattr(billing_app, "db_connect", boom)
    billing_app.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    try:
        assert client.get("/health").status_code == 500
    finally:
        billing_app.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=None)


def test_index_renders_plans(client, fake_db):
    fake_db.result = (["code", "monthly_fee", "included_units"], [("STARTER", Decimal("49.00"), 100)])
    response = client.get("/")
    assert response.status_code == 200
    assert "STARTER — 49.00 / 100 units" in response.get_data(as_text=True)
    assert fake_db.calls == [("SELECT * FROM billing.fn_list_plans()", ())]


def test_plans(client, fake_db):
    fake_db.result = (["code"], [("STARTER",), ("GROWTH",)])
    assert client.get("/plans").get_json() == [{"code": "STARTER"}, {"code": "GROWTH"}]


@pytest.mark.parametrize("query,expected_on", [("", "2026-02-28"), ("?on=2026-03-15", "2026-03-15")])
def test_entitlement_binds_tenant_and_date(client, fake_db, query, expected_on):
    fake_db.result = (["plan_code"], [("STARTER",)])
    response = client.get(f"/plans/{TENANT}/entitlement{query}")
    assert response.get_json() == [{"plan_code": "STARTER"}]
    assert fake_db.calls == [("SELECT * FROM billing.fn_entitlement(%s, %s)", (TENANT, expected_on))]


def test_change_plan_calls_proc_and_redirects(client, fake_db):
    response = client.post(
        f"/plans/{TENANT}/change",
        data={"plan_id": "plan-2", "effective_on": "2026-03-01"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == f"/plans/{TENANT}/entitlement?on=2026-03-01"
    assert fake_db.calls == [("CALL billing.sp_change_plan(%s, %s, %s)", (TENANT, "plan-2", "2026-03-01"))]


def test_change_plan_missing_field_is_400(client, fake_db):
    response = client.post(f"/plans/{TENANT}/change", data={"plan_id": "plan-2"})
    assert response.status_code == 400
    assert fake_db.calls == []


RATING_BODY = {"tenant_id": TENANT, "period_start": "2026-02-01", "period_end": "2026-02-28"}


def test_rating_preview_accepts_json_without_content_type(client, fake_db):
    fake_db.result = (["billable_units"], [(160,)])
    import json
    response = client.post("/api/rating/preview", data=json.dumps(RATING_BODY))
    assert response.get_json() == [{"billable_units": 160}]
    assert fake_db.calls == [(
        "SELECT * FROM billing.fn_usage_rating(%s, %s, %s)",
        (TENANT, "2026-02-01", "2026-02-28"),
    )]


def test_rating_preview_rejects_invalid_json(client, fake_db):
    assert client.post("/api/rating/preview", data="not json").status_code == 400
    assert fake_db.calls == []


def test_rating_finalize(client, fake_db):
    response = client.post("/api/rating/finalize", json=RATING_BODY)
    assert response.get_json() == {"status": "finalized"}
    assert fake_db.calls == [(
        "CALL billing.sp_finalize_rating(%s, %s, %s)",
        (TENANT, "2026-02-01", "2026-02-28"),
    )]


@pytest.mark.xfail(strict=True, raises=KeyError, reason="missing JSON keys surface as 500 (KeyError), form routes return 400")
@pytest.mark.parametrize("path", ["/api/rating/preview", "/api/rating/finalize"])
def test_rating_missing_json_key_is_400(client, fake_db, path):
    assert client.post(path, json={"tenant_id": TENANT}).status_code == 400


@pytest.mark.parametrize("query,expected", [
    ("", ("2026-02-01", "2026-02-28")),
    ("?period_start=2026-03-01&period_end=2026-03-31", ("2026-03-01", "2026-03-31")),
])
def test_invoice_preview_defaults_and_overrides(client, fake_db, query, expected):
    fake_db.result = (["line_no"], [(1,)])
    assert client.get(f"/api/invoices/{TENANT}/preview{query}").get_json() == [{"line_no": 1}]
    assert fake_db.calls == [("SELECT * FROM billing.fn_invoice_preview(%s, %s, %s)", (TENANT, *expected))]


def test_invoice_issue(client, fake_db):
    response = client.post(
        f"/api/invoices/{TENANT}/issue",
        data={"period_start": "2026-02-01", "period_end": "2026-02-28"},
    )
    assert response.get_json() == {"status": "issued"}
    assert fake_db.calls == [(
        "CALL billing.sp_issue_invoice(%s, %s, %s)", (TENANT, "2026-02-01", "2026-02-28"),
    )]


def test_invoice_issue_ignores_json_body(client, fake_db):
    response = client.post(f"/api/invoices/{TENANT}/issue", json={"period_start": "2026-02-01", "period_end": "2026-02-28"})
    assert response.status_code == 400
    assert fake_db.calls == []


def test_invoice_lines(client, fake_db):
    fake_db.result = (["line_type", "amount"], [("plan", Decimal("149.00"))])
    invoice = "60000000-0000-0000-0000-000000000001"
    assert client.get(f"/api/invoices/{invoice}/lines").get_json() == [{"line_type": "plan", "amount": "149.00"}]
    assert fake_db.calls == [("SELECT * FROM billing.fn_invoice_lines(%s)", (invoice,))]


@pytest.mark.parametrize("query,expected", [("", "2026-02-28"), ("?as_of=2026-03-10", "2026-03-10")])
def test_overdue(client, fake_db, query, expected):
    fake_db.result = (["days_overdue"], [(15,)])
    assert client.get(f"/api/dunning/overdue{query}").get_json() == [{"days_overdue": 15}]
    assert fake_db.calls == [("SELECT * FROM billing.fn_overdue_accounts(%s)", (expected,))]


@pytest.mark.parametrize("path,proc,status", [
    ("/api/dunning/schedule", "sp_schedule_dunning", "scheduled"),
    ("/api/dunning/suspend", "sp_suspend_overdue", "suspended"),
])
def test_dunning_actions(client, fake_db, path, proc, status):
    response = client.post(path, data={"as_of": "2026-02-28"})
    assert response.get_json() == {"status": status}
    assert fake_db.calls == [(f"CALL billing.{proc}(%s)", ("2026-02-28",))]
    assert client.post(path, data={}).status_code == 400
