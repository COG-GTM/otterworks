from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg
from fastapi.testclient import TestClient

import app.main as main
from app.domain import EntitlementRow, PlanRow, SubscriptionRow

TENANT = UUID("00000000-0000-0000-0000-000000000001")
PLAN = UUID("10000000-0000-0000-0000-000000000002")
CREATED = SubscriptionRow(
    UUID("20000000-0000-0000-0000-000000000003"),
    TENANT,
    PLAN,
    date(2026, 3, 1),
    None,
    "active",
    None,
)


class FakeConnection:
    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_repeated_plan_change_returns_conflict(monkeypatch) -> None:
    calls = 0

    def fake_change_plan(*_args: object) -> tuple[list[SubscriptionRow], SubscriptionRow]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise psycopg.errors.UniqueViolation("duplicate subscription")
        return [CREATED], CREATED

    monkeypatch.setattr(main, "migrate", lambda: None)
    monkeypatch.setattr(main, "connect", FakeConnection)
    monkeypatch.setattr(main, "change_plan", fake_change_plan)
    with TestClient(main.app) as client:
        payload = {"plan_id": str(PLAN), "effective_on": "2026-03-01"}
        first = client.post(f"/api/tenants/{TENANT}/plan-change", json=payload)
        second = client.post(f"/api/tenants/{TENANT}/plan-change", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "this plan change has already been requested"


class FakeRepository:
    def __init__(self, _connection: object) -> None:
        pass

    def list_plans(self) -> list[PlanRow]:
        return [
            PlanRow(PLAN, "growth", "growth", Decimal("99"), 1000, Decimal("0.0125"), True),
            PlanRow(TENANT, "retired", "starter", Decimal("1"), 1, Decimal("1"), False),
        ]

    def find_entitlements(self, tenant_id: UUID) -> list[EntitlementRow]:
        return [
            EntitlementRow(
                tenant_id, "growth", "growth", Decimal("99"), 1000, "active", None, date(2026, 3, 1)
            )
        ]


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, "migrate", lambda: None)
    monkeypatch.setattr(main, "connect", FakeConnection)
    monkeypatch.setattr(main, "PostgresPlansRepository", FakeRepository)
    return TestClient(main.app)


def test_list_plans_serializes_active_catalog(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        response = client.get("/api/plans")

    assert response.status_code == 200
    assert response.json() == [
        {
            "plan_id": str(PLAN),
            "code": "growth",
            "tier": "growth",
            "monthly_fee": "99.00",
            "included_units": 1000,
            "overage_rate": "0.012500",
        }
    ]


def test_entitlement_parses_query_date_and_serializes(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        found = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "2026-04-15"})
        missing = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "2026-01-01"})
        invalid = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "not-a-date"})

    assert found.status_code == 200
    assert found.json() == {
        "tenant_id": str(TENANT),
        "plan_code": "growth",
        "tier": "growth",
        "monthly_fee": "99.00",
        "included_units": 1000,
        "subscription_status": "active",
        "effective_on": "2026-04-15",
    }
    assert missing.status_code == 404
    assert invalid.status_code == 422
