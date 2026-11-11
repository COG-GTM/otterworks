from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import settings
from app.domain import EntitlementRow, SubscriptionRow

TENANT_A = UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = UUID("00000000-0000-0000-0000-000000000002")
PLAN = UUID("10000000-0000-0000-0000-000000000002")
SERVICE = {"Authorization": f"Bearer {settings.service_token}"}
PAYLOAD = {"plan_id": str(PLAN), "effective_on": "2026-03-01"}


class FakeConnection:
    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def token_for(tenant: object, secret: str | None = None, **overrides: object) -> dict[str, str]:
    claims = {
        "sub": "user-1",
        "tenant_id": str(tenant),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        **overrides,
    }
    encoded = jwt.encode(claims, secret or settings.jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {encoded}"}


@pytest.fixture
def client(monkeypatch):
    calls: dict[str, list] = {"change_plan": [], "reset": []}

    def fake_change_plan(_repository, tenant_id, plan_id, effective_on):
        calls["change_plan"].append(tenant_id)
        row = SubscriptionRow(PLAN, tenant_id, plan_id, effective_on, None, "active", None)
        return [row], row

    def fake_entitlement(_rows, tenant_id, on):
        return EntitlementRow(
            tenant_id, "GROWTH", "growth", Decimal("99"), 1000, "active", None, on
        )

    monkeypatch.setattr(main, "migrate", lambda: None)
    monkeypatch.setattr(main, "connect", FakeConnection)
    monkeypatch.setattr(main, "change_plan", fake_change_plan)
    monkeypatch.setattr(main, "entitlement", fake_entitlement)
    monkeypatch.setattr(main, "PostgresPlansRepository", lambda _c: _FakeRepo())
    monkeypatch.setattr(main, "reset", lambda: calls["reset"].append(True))
    with TestClient(main.app) as test_client:
        test_client.calls = calls
        yield test_client


class _FakeRepo:
    def find_entitlements(self, _tenant_id):
        return []


def plan_change(client: TestClient, tenant: UUID, headers: dict[str, str] | None = None):
    return client.post(f"/api/tenants/{tenant}/plan-change", json=PAYLOAD, headers=headers or {})


def test_plan_change_without_credentials_is_401(client) -> None:
    response = plan_change(client, TENANT_A)
    assert response.status_code == 401
    assert client.calls["change_plan"] == []


def test_plan_change_with_other_tenant_token_is_403(client) -> None:
    response = plan_change(client, TENANT_A, token_for(TENANT_B))
    assert response.status_code == 403
    assert client.calls["change_plan"] == []


def test_plan_change_with_matching_tenant_token_succeeds(client) -> None:
    response = plan_change(client, TENANT_A, token_for(TENANT_A))
    assert response.status_code == 200
    assert client.calls["change_plan"] == [TENANT_A]


def test_plan_change_with_service_token_succeeds(client) -> None:
    assert plan_change(client, TENANT_B, SERVICE).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        token_for(TENANT_A, secret="wrong-secret-0123456789abcdef0123"),
        token_for(TENANT_A, exp=datetime.now(UTC) - timedelta(minutes=1)),
    ],
)
def test_plan_change_with_invalid_token_is_401(client, headers) -> None:
    assert plan_change(client, TENANT_A, headers).status_code == 401
    assert client.calls["change_plan"] == []


def test_plan_change_with_token_missing_tenant_claim_is_403(client) -> None:
    assert plan_change(client, TENANT_A, token_for(None)).status_code == 403


def test_unsigned_token_is_rejected(client) -> None:
    claims = {"sub": "u", "tenant_id": str(TENANT_A), "exp": 9999999999}
    unsigned = jwt.encode(claims, None, algorithm="none")
    headers = {"Authorization": f"Bearer {unsigned}"}
    assert plan_change(client, TENANT_A, headers).status_code == 401


def test_entitlement_requires_matching_tenant(client) -> None:
    url = f"/api/tenants/{TENANT_A}/entitlement?on={date(2026, 3, 1).isoformat()}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=token_for(TENANT_B)).status_code == 403
    assert client.get(url, headers=token_for(TENANT_A)).status_code == 200


def test_reset_requires_service_token(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "allow_internal_reset", True)
    assert client.post("/internal/reset").status_code == 401
    assert client.post("/internal/reset", headers=token_for(TENANT_A)).status_code == 403
    assert client.calls["reset"] == []
    assert client.post("/internal/reset", headers=SERVICE).status_code == 204
    assert client.calls["reset"] == [True]


def test_reset_stays_disabled_without_flag(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "allow_internal_reset", False)
    assert client.post("/internal/reset", headers=SERVICE).status_code == 404
    assert client.calls["reset"] == []


def test_service_token_unset_fails_closed(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "service_token", None)
    monkeypatch.setattr(settings, "allow_internal_reset", True)
    assert client.post("/internal/reset", headers={"Authorization": "Bearer "}).status_code in {
        401,
        403,
    }
    assert plan_change(client, TENANT_A, SERVICE).status_code == 401
    assert client.calls["reset"] == []
