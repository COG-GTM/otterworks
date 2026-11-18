from __future__ import annotations

import os
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import db
from app.repository import PostgresPlansRepository

DATABASE_URL = os.environ.get("BILLING_SVC_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set BILLING_SVC_TEST_DATABASE_URL to run Postgres tests"
)

TENANT = UUID("00000000-0000-0000-0000-000000000001")
GROWTH = UUID("10000000-0000-0000-0000-000000000002")
UNKNOWN = UUID("10000000-0000-0000-0000-0000000000ff")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(db.settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(db.settings, "allow_internal_reset", True)
    with TestClient(main.app) as test_client:
        assert test_client.post("/internal/reset").status_code == 204
        yield test_client


def test_repository_reads_seeded_schema(client) -> None:
    with db.connect() as connection:
        repository = PostgresPlansRepository(connection)
        plans = repository.list_plans()
        entitlements = repository.find_entitlements(TENANT)
        subscriptions = repository.list_subscriptions(TENANT)
    assert {plan.code for plan in plans} >= {"STARTER", "GROWTH", "SCALE"}
    assert entitlements and all(row.tenant_id == TENANT for row in entitlements)
    assert subscriptions and all(row.tenant_id == TENANT for row in subscriptions)


def test_http_flow_against_postgres(client) -> None:
    assert client.get("/health").json()["status"] == "healthy"

    plans = client.get("/api/plans").json()
    assert [plan["code"] for plan in plans][:3] == ["STARTER", "GROWTH", "SCALE"]
    assert plans[0]["monthly_fee"] == "49.00"
    assert plans[0]["overage_rate"] == "0.055000"

    entitlement = client.get(
        f"/api/tenants/{TENANT}/entitlement", params={"on": "2026-02-15"}
    ).json()
    assert entitlement["tenant_id"] == str(TENANT)
    assert entitlement["effective_on"] == "2026-02-15"

    payload = {"plan_id": str(GROWTH), "effective_on": "2027-01-01"}
    changed = client.post(f"/api/tenants/{TENANT}/plan-change", json=payload)
    assert changed.status_code == 200
    assert changed.json()["latest_plan"] == str(GROWTH)
    assert changed.json()["latest_start"] == "2027-01-01"
    closed = [item for item in changed.json()["subscriptions"] if item["ends_on"] == "2026-12-31"]
    assert closed

    after = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "2027-01-01"})
    assert after.json()["plan_code"] == "GROWTH"

    duplicate = client.post(f"/api/tenants/{TENANT}/plan-change", json=payload)
    assert duplicate.status_code == 409

    unknown = client.post(
        f"/api/tenants/{TENANT}/plan-change",
        json={"plan_id": str(UNKNOWN), "effective_on": "2027-02-01"},
    )
    assert unknown.status_code == 400

    missing = client.get(f"/api/tenants/{TENANT}/entitlement", params={"on": "2025-01-01"})
    assert missing.status_code == 404


def test_reset_restores_seed(client) -> None:
    payload = {"plan_id": str(GROWTH), "effective_on": "2027-01-01"}
    assert client.post(f"/api/tenants/{TENANT}/plan-change", json=payload).status_code == 200
    db.reset()
    with db.connect() as connection:
        subscriptions = PostgresPlansRepository(connection).list_subscriptions(TENANT)
    assert all(row.starts_on < date(2027, 1, 1) for row in subscriptions)
