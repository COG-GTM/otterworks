"""QA audit: HTTP contract of the billing service with the database stubbed out."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.domain import EntitlementRow, PlanRow, SubscriptionRow

TENANT = UUID("00000000-0000-0000-0000-000000000001")
STARTER = UUID("10000000-0000-0000-0000-000000000001")
GROWTH = UUID("10000000-0000-0000-0000-000000000002")


class FakeConnection:
    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, *_args: object) -> None:
        return None


class FakeRepository:
    plans: list[PlanRow] = []
    entitlements: list[EntitlementRow] = []

    def __init__(self, _connection: object) -> None:
        pass

    def list_plans(self) -> list[PlanRow]:
        return list(self.plans)

    def find_entitlements(self, _tenant_id: UUID) -> list[EntitlementRow]:
        return list(self.entitlements)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "migrate", lambda: None)
    monkeypatch.setattr(main, "connect", FakeConnection)
    monkeypatch.setattr(main, "PostgresPlansRepository", FakeRepository)
    FakeRepository.plans = []
    FakeRepository.entitlements = []
    with TestClient(main.app) as test_client:
        yield test_client


def test_health_reports_healthy(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "billing-service"}


def test_health_returns_503_when_database_down(client, monkeypatch) -> None:
    def broken():
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(main, "connect", broken)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "database unavailable"


def test_list_plans_formats_money_and_rate(client) -> None:
    FakeRepository.plans = [
        PlanRow(GROWTH, "GROWTH", "growth", Decimal("149"), 500, Decimal("0.035"), True),
        PlanRow(STARTER, "STARTER", "starter", Decimal("49"), 100, Decimal("0.055"), True),
        PlanRow(UUID(int=9), "OLD", "starter", Decimal("1"), 1, Decimal("0.1"), False),
    ]
    body = client.get("/api/plans").json()
    assert [item["code"] for item in body] == ["STARTER", "GROWTH"]
    assert body[0] == {
        "plan_id": str(STARTER),
        "code": "STARTER",
        "tier": "starter",
        "monthly_fee": "49.00",
        "included_units": 100,
        "overage_rate": "0.055000",
    }


def test_entitlement_returns_effective_row(client) -> None:
    FakeRepository.entitlements = [
        EntitlementRow(
            TENANT, "STARTER", "starter", Decimal("49"), 100, "active", None, date(2026, 1, 1)
        ),
    ]
    response = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "2026-02-28"})
    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": str(TENANT),
        "plan_code": "STARTER",
        "tier": "starter",
        "monthly_fee": "49.00",
        "included_units": 100,
        "subscription_status": "active",
        "effective_on": "2026-02-28",
    }


def test_entitlement_unknown_tenant_is_404(client) -> None:
    response = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "2026-02-28"})
    assert response.status_code == 404
    assert response.json()["detail"] == "entitlement not found"


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/tenants/not-a-uuid/entitlement", {"on": "2026-02-28"}),
        (f"/api/tenants/{TENANT}/entitlement", {}),
        (f"/api/tenants/{TENANT}/entitlement", {"on": "28/02/2026"}),
    ],
)
def test_entitlement_validates_inputs(client, path, params) -> None:
    assert client.get(path, params=params).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"plan_id": "nope", "effective_on": "2026-03-01"},
        {"plan_id": str(GROWTH), "effective_on": "not-a-date"},
        {"plan_id": str(GROWTH)},
    ],
)
def test_plan_change_validates_body(client, payload) -> None:
    response = client.post(f"/api/tenants/{TENANT}/plan-change", json=payload)
    assert response.status_code == 422


def test_plan_change_unknown_plan_maps_fk_violation_to_400(client, monkeypatch) -> None:
    def fk_violation(*_args):
        raise psycopg.errors.ForeignKeyViolation("fk")

    monkeypatch.setattr(main, "change_plan", fk_violation)
    response = client.post(
        f"/api/tenants/{TENANT}/plan-change",
        json={"plan_id": str(UUID(int=99)), "effective_on": "2026-03-01"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid plan change"


def test_plan_change_success_shape(client, monkeypatch) -> None:
    prior = SubscriptionRow(
        UUID(int=1), TENANT, STARTER, date(2026, 1, 1), date(2026, 2, 28), "active", None
    )
    created = SubscriptionRow(UUID(int=2), TENANT, GROWTH, date(2026, 3, 1), None, "active", None)
    monkeypatch.setattr(main, "change_plan", lambda *_args: ([prior, created], created))
    response = client.post(
        f"/api/tenants/{TENANT}/plan-change",
        json={"plan_id": str(GROWTH), "effective_on": "2026-03-01"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "latest_plan": str(GROWTH),
        "latest_start": "2026-03-01",
        "subscriptions": [
            {
                "plan_id": str(STARTER),
                "starts_on": "2026-01-01",
                "ends_on": "2026-02-28",
                "status": "active",
            },
            {
                "plan_id": str(GROWTH),
                "starts_on": "2026-03-01",
                "ends_on": None,
                "status": "active",
            },
        ],
    }


def test_internal_reset_disabled_by_default(client, monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "allow_internal_reset", False)
    response = client.post("/internal/reset")
    assert response.status_code == 404


def test_internal_reset_enabled_calls_reset(client, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(main.settings, "allow_internal_reset", True)
    monkeypatch.setattr(main, "reset", lambda: calls.append(True))
    response = client.post("/internal/reset")
    assert response.status_code == 204
    assert calls == [True]


def test_internal_reset_rejects_get(client) -> None:
    assert client.get("/internal/reset").status_code == 405


@pytest.mark.xfail(
    reason="QA-BILL-01: billing-service only migrates on startup and never seeds; "
    "/api/plans is empty until POST /internal/reset (app/main.py lifespan)",
    strict=True,
)
def test_startup_seeds_catalog(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(main, "migrate", lambda: calls.append("migrate"))
    monkeypatch.setattr(main, "reset", lambda: calls.append("reset"))
    with TestClient(main.app):
        pass
    assert "reset" in calls or "seed" in calls
