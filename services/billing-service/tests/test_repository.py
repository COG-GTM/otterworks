from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from psycopg.rows import dict_row

import app.db as db
from app.domain import EntitlementRow, PlanRow, SubscriptionRow
from app.repository import PostgresPlansRepository

TENANT = UUID("00000000-0000-0000-0000-000000000001")
PLAN = UUID("10000000-0000-0000-0000-000000000001")
SUBSCRIPTION = UUID("20000000-0000-0000-0000-000000000001")


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, tuple | None]] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> FakeCursor:
        self.calls.append((" ".join(sql.split()), params))
        return FakeCursor(self.rows)


def test_list_plans_maps_rows_to_plan_rows() -> None:
    connection = FakeConnection(
        [
            {
                "id": PLAN,
                "code": "STARTER",
                "tier": "starter",
                "monthly_fee": "49.00",
                "included_units": 100,
                "overage_rate": 0.055,
                "active": True,
            }
        ]
    )
    plans = PostgresPlansRepository(connection).list_plans()
    assert plans == [
        PlanRow(PLAN, "STARTER", "starter", Decimal("49.00"), 100, Decimal(0.055), True)
    ]
    sql, params = connection.calls[0]
    assert sql.startswith("SELECT id, code, tier, monthly_fee") and "FROM billing_svc.plans" in sql
    assert params is None


def test_find_entitlements_filters_by_tenant() -> None:
    connection = FakeConnection(
        [
            {
                "tenant_id": TENANT,
                "plan_code": "STARTER",
                "tier": "starter",
                "monthly_fee": Decimal("49.00"),
                "included_units": 100,
                "status": "active",
                "starts_on": date(2026, 1, 1),
                "ends_on": None,
            }
        ]
    )
    rows = PostgresPlansRepository(connection).find_entitlements(TENANT)
    assert rows == [
        EntitlementRow(
            TENANT, "STARTER", "starter", Decimal("49.00"), 100, "active", None, date(2026, 1, 1)
        )
    ]
    sql, params = connection.calls[0]
    assert "JOIN billing_svc.subscriptions s" in sql and "WHERE t.id = %s" in sql
    assert params == (TENANT,)


def test_list_subscriptions_maps_rows() -> None:
    connection = FakeConnection(
        [
            {
                "id": SUBSCRIPTION,
                "tenant_id": TENANT,
                "plan_id": PLAN,
                "starts_on": date(2026, 1, 1),
                "ends_on": date(2026, 2, 28),
                "status": "suspended",
                "suspended_on": date(2026, 2, 1),
            }
        ]
    )
    rows = PostgresPlansRepository(connection).list_subscriptions(TENANT)
    assert rows == [
        SubscriptionRow(
            SUBSCRIPTION,
            TENANT,
            PLAN,
            date(2026, 1, 1),
            date(2026, 2, 28),
            "suspended",
            date(2026, 2, 1),
        )
    ]
    sql, params = connection.calls[0]
    assert "FROM billing_svc.subscriptions WHERE tenant_id = %s" in sql
    assert params == (TENANT,)


def test_update_subscription_issues_update() -> None:
    connection = FakeConnection()
    PostgresPlansRepository(connection).update_subscription(
        SUBSCRIPTION, date(2026, 2, 28), "active"
    )
    sql, params = connection.calls[0]
    assert sql == ("UPDATE billing_svc.subscriptions SET ends_on = %s, status = %s WHERE id = %s")
    assert params == (date(2026, 2, 28), "active", SUBSCRIPTION)


def test_insert_subscription_issues_insert() -> None:
    connection = FakeConnection()
    PostgresPlansRepository(connection).insert_subscription(
        SUBSCRIPTION, TENANT, PLAN, date(2026, 3, 1), "active"
    )
    sql, params = connection.calls[0]
    assert sql.startswith("INSERT INTO billing_svc.subscriptions (id, tenant_id, plan_id")
    assert params == (SUBSCRIPTION, TENANT, PLAN, date(2026, 3, 1), "active")


def test_connect_uses_configured_url_and_dict_rows(monkeypatch) -> None:
    captured: dict = {}

    def fake_connect(url: str, **kwargs: object) -> str:
        captured["url"] = url
        captured.update(kwargs)
        return "connection"

    monkeypatch.setattr(db.settings, "database_url", "postgresql://example/billing")
    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    assert db.connect() == "connection"
    assert captured == {"url": "postgresql://example/billing", "row_factory": dict_row}


def test_migrate_applies_initial_migration(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(db, "connect", lambda: connection)
    db.migrate()
    assert [sql for sql, _ in connection.calls] == [" ".join(db.MIGRATION.read_text().split())]


def test_reset_migrates_truncates_and_reseeds(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(db, "connect", lambda: connection)
    db.reset()
    statements = [sql for sql, _ in connection.calls]
    assert statements == [
        " ".join(db.MIGRATION.read_text().split()),
        "TRUNCATE TABLE billing_svc.subscriptions, billing_svc.plans, billing_svc.tenants",
        " ".join(db.SEED.read_text().split()),
    ]
