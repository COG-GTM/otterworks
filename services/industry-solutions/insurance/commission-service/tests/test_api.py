"""HTTP edge tests against a real PostgreSQL (non-superuser role so RLS applies).

Set COMMISSION_TEST_DATABASE_URL to run; skipped otherwise.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Iterator

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DATABASE_URL = os.environ.get("COMMISSION_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="COMMISSION_TEST_DATABASE_URL not set"),
]
SECRET = secrets.token_urlsafe(48)
BASE = "/api/v1/commission"


def bearer(tenant: str = "northwind-mutual", roles: list[str] | None = None) -> dict[str, str]:
    claims = {
        "sub": "tester@otterworks.test",
        "tenant_id": tenant,
        "roles": roles if roles is not None else ["ADMIN"],
        "type": "access",
        "exp": int(time.time()) + 300,
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        database_url=DATABASE_URL, JWT_SECRET=SECRET, enable_reset=True
    )
    with TestClient(create_app(settings)) as test_client:
        for tenant in ("northwind-mutual", "contoso-life"):
            assert (
                test_client.post(f"{BASE}/internal/reset", headers=bearer(tenant)).status_code
                == 200
            )
        yield test_client


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"{BASE}/ledger"),
        ("get", f"{BASE}/rates?product_code=AUTO-STD"),
        ("put", f"{BASE}/rates"),
        ("post", f"{BASE}/etl/loads"),
    ],
)
def test_every_endpoint_requires_a_token(client: TestClient, method: str, path: str) -> None:
    assert getattr(client, method)(path).status_code == 401


def test_forged_identity_headers_are_ignored(client: TestClient) -> None:
    response = client.get(f"{BASE}/ledger", headers={"X-User-ID": "admin", "X-Tenant-ID": "x"})
    assert response.status_code == 401


@pytest.mark.rule("INS-CALC-003")
def test_three_way_split_via_http(client: TestClient) -> None:
    response = client.post(
        f"{BASE}/policies/4/calculations", json={"period_month": "2025-06"}, headers=bearer()
    )
    assert response.status_code == 200
    assert [row["commission_amt"] for row in response.json()["rows"]] == [
        "38.00",
        "19.20",
        "12.80",
    ]


def test_roles_enforced(client: TestClient) -> None:
    viewer = bearer(roles=["COMMISSION_VIEWER"])
    manager = bearer(roles=["COMMISSION_MANAGER"])
    plain_user = bearer(roles=["USER"])
    rate = {"product_code": "AUTO-STD", "rate_pct": "8.5", "effective_from": "2025-07-01"}
    assert client.get(f"{BASE}/ledger", headers=plain_user).status_code == 403
    assert client.get(f"{BASE}/ledger", headers=viewer).status_code == 200
    assert client.put(f"{BASE}/rates", json=rate, headers=viewer).status_code == 403
    assert client.put(f"{BASE}/rates", json=rate, headers=manager).status_code == 403
    calc = {"period_month": "2025-06"}
    assert (
        client.post(f"{BASE}/policies/1/calculations", json=calc, headers=viewer).status_code == 403
    )
    assert (
        client.post(f"{BASE}/policies/1/calculations", json=calc, headers=manager).status_code
        == 200
    )
    assert client.post(f"{BASE}/etl/loads", json={}, headers=manager).status_code == 403
    assert client.get(f"{BASE}/audit", headers=manager).status_code == 403


def test_business_errors_carry_legacy_codes(client: TestClient) -> None:
    response = client.post(
        f"{BASE}/policies/5/calculations", json={"period_month": "2025-06"}, headers=bearer()
    )
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "POLICY_NOT_ACTIVE",
        "legacy_ora_code": -20008,
        "message": "Policy 5 is LAPSED",
    }


def test_tenants_cannot_read_each_other(client: TestClient) -> None:
    client.post(
        f"{BASE}/policies/4/calculations", json={"period_month": "2025-06"}, headers=bearer()
    )
    contoso = bearer("contoso-life")
    assert client.get(f"{BASE}/ledger?policy_id=4", headers=contoso).json() == []
    rates = client.get(f"{BASE}/rates?product_code=AUTO-STD", headers=contoso).json()
    assert [r["rate_pct"] for r in rates] == ["12.00"]
    # Same natural policy id, the tenant's own data.
    own = client.post(
        f"{BASE}/policies/4/calculations", json={"period_month": "2025-06"}, headers=contoso
    )
    assert [r["commission_amt"] for r in own.json()["rows"]] == ["120.00"]
    # Policy 2 exists only for northwind; contoso gets the not-found contract, not the data.
    assert client.get(f"{BASE}/policies/2/splits", headers=contoso).status_code == 404
    north = client.get(f"{BASE}/ledger?policy_id=4", headers=bearer()).json()
    assert [r["commission_amt"] for r in north] == ["38.00", "19.20", "12.80"]


def test_unknown_tenant_sees_nothing(client: TestClient) -> None:
    stranger = bearer("unknown-co")
    assert client.get(f"{BASE}/ledger", headers=stranger).json() == []
    response = client.post(
        f"{BASE}/policies/4/calculations", json={"period_month": "2025-06"}, headers=stranger
    )
    assert response.status_code == 404


def test_row_level_security_backstop() -> None:
    """Even a raw query without a tenant filter only sees the bound tenant."""
    assert DATABASE_URL
    with psycopg.connect(DATABASE_URL) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.tenant_id', 'contoso-life', true)")
        tenants = connection.execute(
            "SELECT DISTINCT tenant_id FROM commission.policies"
        ).fetchall()
        assert tenants == [("contoso-life",)]
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM commission.policies").fetchone() == (0,)


def test_reset_disabled_by_default() -> None:
    settings = Settings(database_url=DATABASE_URL, JWT_SECRET=SECRET, enable_reset=False)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as test_client:
        assert test_client.post(f"{BASE}/internal/reset", headers=bearer()).status_code == 404
