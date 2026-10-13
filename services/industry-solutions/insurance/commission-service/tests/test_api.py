"""HTTP edge tests against a real PostgreSQL (non-superuser role so RLS applies).

Set COMMISSION_TEST_DATABASE_URL to run; skipped otherwise.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.domain import calculation, rates, splits
from app.main import create_app
from app.repository import PostgresCommissionRepository

DATABASE_URL = os.environ.get("COMMISSION_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="COMMISSION_TEST_DATABASE_URL not set"),
]
SECRET = secrets.token_urlsafe(48)
BASE = "/api/v1/commission"
RESET = ["COMMISSION_PARITY_RESET"]
TENANT = "northwind-mutual"


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
        database_url=DATABASE_URL,
        JWT_SECRET=SECRET,
        enable_reset=True,
        reset_tenants="northwind-mutual,contoso-life",
    )
    with TestClient(create_app(settings)) as test_client:
        for tenant in ("northwind-mutual", "contoso-life"):
            reset = test_client.post(f"{BASE}/internal/reset", headers=bearer(tenant, RESET))
            assert reset.status_code == 200
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
        reset = test_client.post(f"{BASE}/internal/reset", headers=bearer(roles=RESET))
        assert reset.status_code == 404


def test_reset_needs_parity_role_and_allowlisted_tenant(client: TestClient) -> None:
    assert client.post(f"{BASE}/internal/reset", headers=bearer()).status_code == 403
    stranger = bearer("unlisted-tenant", RESET)
    assert client.post(f"{BASE}/internal/reset", headers=stranger).status_code == 404


Step = Callable[[PostgresCommissionRepository], object]


def race(first: Step, second: Step) -> None:
    """Run `second` while `first` holds its transaction open; `second` must wait, then succeed."""
    assert DATABASE_URL
    db = Database(DATABASE_URL)
    errors: list[BaseException] = []

    def run_second() -> None:
        try:
            with db.tenant_transaction(TENANT) as connection:
                second(PostgresCommissionRepository(connection, TENANT))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with db.tenant_transaction(TENANT) as connection:
        first(PostgresCommissionRepository(connection, TENANT))
        worker = threading.Thread(target=run_second)
        worker.start()
        worker.join(0.5)
        assert worker.is_alive(), "second writer did not wait for the first"
    worker.join(10)
    assert not errors, errors


def test_concurrent_rate_supersessions_serialise(client: TestClient) -> None:
    def supersede(pct: str, start: date) -> Step:
        return lambda r: rates.upsert_commission_rate(r, "TERM-20", None, Decimal(pct), start, "t")

    race(supersede("16", date(2025, 7, 1)), supersede("17", date(2025, 8, 1)))
    rows = client.get(f"{BASE}/rates", params={"product_code": "TERM-20"}, headers=bearer()).json()
    history = [(r["rate_pct"], r["effective_from"], r["effective_to"]) for r in rows]
    assert ("16.00", "2025-07-01", "2025-07-31") in history
    assert [h for h in history if h[2] is None] == [("17.00", "2025-08-01", None)]


def test_concurrent_split_replacements_never_overallocate(client: TestClient) -> None:
    race(
        lambda r: splits.set_commission_splits(r, 3, [(1, Decimal("100"))], "a"),
        lambda r: splits.set_commission_splits(r, 3, [(2, Decimal("100"))], "b"),
    )
    rows = client.get(f"{BASE}/policies/3/splits", headers=bearer()).json()["splits"]
    assert [(r["agent_id"], r["split_pct"]) for r in rows] == [(2, "100.00")]


def test_concurrent_calculations_of_an_empty_period(client: TestClient) -> None:
    race(
        lambda r: calculation.calculate_policy_commission(r, 1, "2025-07", "a"),
        lambda r: calculation.calculate_policy_commission(r, 1, "2025-07", "b"),
    )
    rows = client.get(
        f"{BASE}/ledger", params={"policy_id": 1, "period_month": "2025-07"}, headers=bearer()
    ).json()
    assert len(rows) == 1


@pytest.mark.parametrize("period", ["0000-01", "\uff12\uff10\uff12\uff15-06"])
def test_bad_periods_are_business_errors_not_500(client: TestClient, period: str) -> None:
    response = client.post(
        f"{BASE}/policies/1/calculations", json={"period_month": period}, headers=bearer()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PERIOD"
