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
LEGACY = UUID("10000000-0000-0000-0000-000000000009")
SUBSCRIPTION = UUID("20000000-0000-0000-0000-000000000001")


class FakeConnection:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.statements: list[str] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        if self.error is not None:
            raise self.error
        self.statements.append(statement)


class FakeRepository:
    plans: list[PlanRow] = []
    entitlements: list[EntitlementRow] = []
    subscriptions: list[SubscriptionRow] = []

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def list_plans(self) -> list[PlanRow]:
        return list(self.plans)

    def find_entitlements(self, tenant_id: UUID) -> list[EntitlementRow]:
        return [row for row in self.entitlements if row.tenant_id == tenant_id]

    def list_subscriptions(self, tenant_id: UUID) -> list[SubscriptionRow]:
        return [row for row in FakeRepository.subscriptions if row.tenant_id == tenant_id]

    def update_subscription(self, subscription_id: UUID, ends_on: date, status: str) -> None:
        FakeRepository.subscriptions = [
            SubscriptionRow(
                row.subscription_id,
                row.tenant_id,
                row.plan_id,
                row.starts_on,
                ends_on,
                status,
                row.suspended_on,
            )
            if row.subscription_id == subscription_id
            else row
            for row in FakeRepository.subscriptions
        ]

    def insert_subscription(
        self,
        subscription_id: UUID,
        tenant_id: UUID,
        plan_id: UUID,
        starts_on: date,
        status: str,
    ) -> None:
        FakeRepository.subscriptions.append(
            SubscriptionRow(subscription_id, tenant_id, plan_id, starts_on, None, status, None)
        )


@pytest.fixture
def connection() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def client(monkeypatch, connection):
    migrations: list[bool] = []
    monkeypatch.setattr(main, "migrate", lambda: migrations.append(True))
    monkeypatch.setattr(main, "connect", lambda: connection)
    monkeypatch.setattr(main, "PostgresPlansRepository", FakeRepository)
    monkeypatch.setattr(FakeRepository, "plans", [])
    monkeypatch.setattr(FakeRepository, "entitlements", [])
    monkeypatch.setattr(FakeRepository, "subscriptions", [])
    with TestClient(main.app) as test_client:
        assert migrations == [True]
        yield test_client


def test_health_reports_healthy(client, connection) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "billing-service"}
    assert connection.statements == ["SELECT 1"]


def test_health_returns_503_when_database_unavailable(client, connection) -> None:
    connection.error = psycopg.OperationalError("down")
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "database unavailable"


def test_internal_reset_disabled_by_default(client, monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(main, "reset", lambda: calls.append(True))
    monkeypatch.setattr(main.settings, "allow_internal_reset", False)
    response = client.post("/internal/reset")
    assert response.status_code == 404
    assert response.json()["detail"] == "internal reset is disabled"
    assert calls == []


def test_internal_reset_runs_when_enabled(client, monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(main, "reset", lambda: calls.append(True))
    monkeypatch.setattr(main.settings, "allow_internal_reset", True)
    response = client.post("/internal/reset")
    assert response.status_code == 204
    assert response.content == b""
    assert calls == [True]


def test_list_plans_returns_active_catalog_with_formatted_decimals(client) -> None:
    FakeRepository.plans = [
        PlanRow(GROWTH, "GROWTH", "growth", Decimal("149"), 500, Decimal("0.035"), True),
        PlanRow(LEGACY, "LEGACY", "starter", Decimal("9"), 10, Decimal("0.1"), False),
        PlanRow(STARTER, "STARTER", "starter", Decimal("49"), 100, Decimal("0.055"), True),
    ]
    response = client.get("/api/plans")
    assert response.status_code == 200
    assert response.json() == [
        {
            "plan_id": str(STARTER),
            "code": "STARTER",
            "tier": "starter",
            "monthly_fee": "49.00",
            "included_units": 100,
            "overage_rate": "0.055000",
        },
        {
            "plan_id": str(GROWTH),
            "code": "GROWTH",
            "tier": "growth",
            "monthly_fee": "149.00",
            "included_units": 500,
            "overage_rate": "0.035000",
        },
    ]


def test_entitlement_returns_effective_subscription(client) -> None:
    FakeRepository.entitlements = [
        EntitlementRow(
            TENANT,
            "STARTER",
            "starter",
            Decimal("49"),
            100,
            "active",
            date(2026, 2, 28),
            date(2026, 1, 1),
        ),
        EntitlementRow(
            TENANT,
            "GROWTH",
            "growth",
            Decimal("149.5"),
            500,
            "suspended",
            None,
            date(2026, 3, 1),
        ),
    ]
    response = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "2026-03-15"})
    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": str(TENANT),
        "plan_code": "GROWTH",
        "tier": "growth",
        "monthly_fee": "149.50",
        "included_units": 500,
        "subscription_status": "suspended",
        "effective_on": "2026-03-15",
    }


def test_entitlement_returns_404_when_no_subscription_is_effective(client) -> None:
    FakeRepository.entitlements = [
        EntitlementRow(
            TENANT, "GROWTH", "growth", Decimal("149"), 500, "active", None, date(2026, 3, 1)
        ),
    ]
    response = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "2026-02-01"})
    assert response.status_code == 404
    assert response.json()["detail"] == "entitlement not found"


def test_entitlement_requires_on_date(client) -> None:
    response = client.get(f"/api/tenants/{TENANT}/entitlement")
    assert response.status_code == 422


def test_plan_change_returns_full_subscription_history(client) -> None:
    FakeRepository.subscriptions = [
        SubscriptionRow(SUBSCRIPTION, TENANT, STARTER, date(2026, 1, 1), None, "active", None)
    ]
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


def test_plan_change_maps_foreign_key_violation_to_400(client, monkeypatch) -> None:
    def fail(*_args: object) -> None:
        raise psycopg.errors.ForeignKeyViolation("unknown plan")

    monkeypatch.setattr(main, "change_plan", fail)
    response = client.post(
        f"/api/tenants/{TENANT}/plan-change",
        json={"plan_id": str(LEGACY), "effective_on": "2026-03-01"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid plan change"


@pytest.mark.parametrize(
    ("tenant", "payload"),
    [
        ("not-a-uuid", {"plan_id": str(GROWTH), "effective_on": "2026-03-01"}),
        (str(TENANT), {"plan_id": "nope", "effective_on": "2026-03-01"}),
        (str(TENANT), {"plan_id": str(GROWTH), "effective_on": "2026-13-01"}),
        (str(TENANT), {"plan_id": str(GROWTH)}),
    ],
)
def test_plan_change_rejects_invalid_input(client, tenant, payload) -> None:
    response = client.post(f"/api/tenants/{tenant}/plan-change", json=payload)
    assert response.status_code == 422
