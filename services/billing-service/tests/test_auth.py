from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import encode_token
from app.config import settings
from app.domain import EntitlementRow, PlanRow, SubscriptionRow

TENANT_A = UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = UUID("00000000-0000-0000-0000-000000000002")
PLAN = UUID("10000000-0000-0000-0000-000000000002")
FAR_FUTURE = 4102444800


def token(secret: str | None = None, alg: str = "HS256", **overrides: object) -> str:
    claims: dict[str, object] = {"sub": "user-1", "type": "access", "exp": FAR_FUTURE}
    claims.update(overrides)
    return encode_token(
        {key: value for key, value in claims.items() if value is not None},
        secret or settings.jwt_secret,
        alg,
    )


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


class FakeConnection:
    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str) -> None:
        return None


class FakeRepository:
    def __init__(self, _connection: object) -> None:
        pass

    def list_plans(self) -> list[PlanRow]:
        return [PlanRow(PLAN, "GROWTH", "growth", Decimal("49"), 1000, Decimal("0.01"), True)]

    def find_entitlements(self, tenant_id: UUID) -> list[EntitlementRow]:
        return [
            EntitlementRow(
                tenant_id,
                "GROWTH",
                "growth",
                Decimal("49"),
                1000,
                "active",
                None,
                date(2026, 1, 1),
            )
        ]


@pytest.fixture
def state(monkeypatch) -> dict[str, list]:
    calls: dict[str, list] = {"change_plan": [], "reset": []}

    def fake_change_plan(_repo, tenant_id, plan_id, effective_on):
        calls["change_plan"].append(tenant_id)
        row = SubscriptionRow(PLAN, tenant_id, plan_id, effective_on, None, "active", None)
        return [row], row

    monkeypatch.setattr(main, "migrate", lambda: None)
    monkeypatch.setattr(main, "connect", FakeConnection)
    monkeypatch.setattr(main, "PostgresPlansRepository", FakeRepository)
    monkeypatch.setattr(main, "change_plan", fake_change_plan)
    monkeypatch.setattr(main, "reset", lambda: calls["reset"].append(True))
    return calls


@pytest.fixture
def client(state) -> TestClient:
    with TestClient(main.app) as test_client:
        yield test_client


def entitlement_url(tenant: UUID) -> str:
    return f"/api/tenants/{tenant}/entitlement?on=2026-03-01"


def plan_change(client: TestClient, tenant: UUID, headers: dict[str, str] | None = None):
    return client.post(
        f"/api/tenants/{tenant}/plan-change",
        json={"plan_id": str(PLAN), "effective_on": "2026-03-01"},
        headers=headers or {},
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/plans"),
        ("GET", entitlement_url(TENANT_A)),
        ("POST", f"/api/tenants/{TENANT_A}/plan-change"),
    ],
)
def test_api_requires_bearer_token(client: TestClient, state, method: str, path: str) -> None:
    response = client.request(
        method, path, json={"plan_id": str(PLAN), "effective_on": "2026-03-01"}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert state["change_plan"] == []


@pytest.mark.parametrize(
    "bad_token",
    [
        token(secret="another-secret-that-is-long-enough-000000"),
        token(exp=int(time.time()) - 3600),
        token(exp=None),
        token(exp=float("nan")),
        token(exp=float("inf")),
        token(nbf=float("nan")),
        token(nbf="2026-01-01"),
        token(alg="HS512", secret="another-secret-that-is-long-enough-000000"),
        token(type="refresh"),
        token(sub=None),
        token(tenant_id="not-a-uuid"),
        token(roles="ADMIN"),
        "not.a.jwt",
        "garbage",
    ],
)
def test_invalid_tokens_are_rejected(client: TestClient, state, bad_token: str) -> None:
    response = plan_change(client, TENANT_A, bearer(bad_token))
    assert response.status_code == 401
    assert state["change_plan"] == []


def test_alg_none_token_is_rejected(client: TestClient, state) -> None:
    header, payload, _signature = token(tenant_id=str(TENANT_A), roles=["ADMIN"]).split(".")
    none_header = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"
    assert plan_change(client, TENANT_A, bearer(f"{none_header}.{payload}.")).status_code == 401
    assert plan_change(client, TENANT_A, bearer(f"{header}.{payload}.")).status_code == 401
    assert state["change_plan"] == []


@pytest.mark.parametrize("alg", ["HS256", "HS384", "HS512"])
def test_platform_hmac_algorithms_are_accepted(client: TestClient, alg: str) -> None:
    response = client.get("/api/plans", headers=bearer(token(alg=alg)))
    assert response.status_code == 200


def test_algorithm_swap_invalidates_signature(client: TestClient) -> None:
    header, _payload, signature = token(alg="HS512").split(".")
    _header, payload, _signature = token(alg="HS512", roles=["ADMIN"]).split(".")
    response = client.get("/api/plans", headers=bearer(f"{header}.{payload}.{signature}"))
    assert response.status_code == 401


def test_tenant_caller_reads_own_entitlement(client: TestClient) -> None:
    response = client.get(entitlement_url(TENANT_A), headers=bearer(token(tenant_id=str(TENANT_A))))
    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(TENANT_A)


def test_tenant_caller_cannot_read_other_tenant(client: TestClient) -> None:
    response = client.get(entitlement_url(TENANT_B), headers=bearer(token(tenant_id=str(TENANT_A))))
    assert response.status_code == 403


def test_caller_without_tenant_claim_is_forbidden(client: TestClient, state) -> None:
    headers = bearer(token(roles=["USER"]))
    assert client.get(entitlement_url(TENANT_A), headers=headers).status_code == 403
    assert plan_change(client, TENANT_A, headers).status_code == 403
    assert state["change_plan"] == []


def test_tenant_caller_cannot_change_other_tenant_plan(client: TestClient, state) -> None:
    response = plan_change(client, TENANT_B, bearer(token(tenant_id=str(TENANT_A))))
    assert response.status_code == 403
    assert state["change_plan"] == []


def test_tenant_caller_changes_own_plan(client: TestClient, state) -> None:
    response = plan_change(client, TENANT_A, bearer(token(tenant_id=str(TENANT_A))))
    assert response.status_code == 200
    assert state["change_plan"] == [TENANT_A]


def test_admin_may_operate_on_any_tenant(client: TestClient, state) -> None:
    headers = bearer(token(roles=["ADMIN"]))
    assert client.get(entitlement_url(TENANT_B), headers=headers).status_code == 200
    assert plan_change(client, TENANT_B, headers).status_code == 200
    assert state["change_plan"] == [TENANT_B]


def test_authenticated_caller_lists_plans(client: TestClient) -> None:
    response = client.get("/api/plans", headers=bearer(token()))
    assert response.status_code == 200
    assert response.json()[0]["code"] == "GROWTH"


def test_missing_jwt_secret_fails_closed(client: TestClient, monkeypatch, state) -> None:
    monkeypatch.setattr(settings, "jwt_secret", "")
    forged = encode_token({"sub": "x", "type": "access", "exp": FAR_FUTURE, "roles": ["ADMIN"]}, "")
    response = plan_change(client, TENANT_A, bearer(forged))
    assert response.status_code == 503
    assert state["change_plan"] == []


def test_reset_disabled_without_flag(client: TestClient, monkeypatch, state) -> None:
    monkeypatch.setattr(settings, "allow_internal_reset", False)
    response = client.post(
        "/internal/reset", headers={"X-Internal-Reset-Token": settings.internal_reset_token}
    )
    assert response.status_code == 404
    assert state["reset"] == []


def test_reset_disabled_without_configured_token(client: TestClient, monkeypatch, state) -> None:
    monkeypatch.setattr(settings, "allow_internal_reset", True)
    monkeypatch.setattr(settings, "internal_reset_token", "")
    response = client.post("/internal/reset", headers={"X-Internal-Reset-Token": ""})
    assert response.status_code == 404
    assert state["reset"] == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Internal-Reset-Token": "wrong-token"},
        {"Authorization": f"Bearer {token(roles=['ADMIN'])}"},
    ],
)
def test_reset_requires_reset_token_even_when_enabled(
    client: TestClient, monkeypatch, state, headers: dict[str, str]
) -> None:
    monkeypatch.setattr(settings, "allow_internal_reset", True)
    response = client.post("/internal/reset", headers=headers)
    assert response.status_code == 403
    assert state["reset"] == []


def test_reset_with_flag_and_token(client: TestClient, monkeypatch, state) -> None:
    monkeypatch.setattr(settings, "allow_internal_reset", True)
    response = client.post(
        "/internal/reset", headers={"X-Internal-Reset-Token": settings.internal_reset_token}
    )
    assert response.status_code == 204
    assert state["reset"] == [True]


def test_health_stays_public(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
