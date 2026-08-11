from pathlib import Path

import pytest


@pytest.mark.rule("PLANS-001")
def test_catalog(client):
    response = client.get("/api/plans")
    assert response.status_code == 200
    assert [plan["code"] for plan in response.json()] == ["STARTER", "GROWTH", "SCALE"]


@pytest.mark.rule("PLANS-002")
def test_entitlement(client):
    response = client.get(
        "/api/tenants/00000000-0000-0000-0000-000000000001/entitlement",
        params={"on": "2026-02-28"},
    )
    assert response.status_code == 200
    assert response.json()["plan_code"] == "STARTER"
    assert response.json()["subscription_status"] == "active"


@pytest.mark.rule("PLANS-003")
def test_suspended_entitlement(client):
    response = client.get(
        "/api/tenants/00000000-0000-0000-0000-000000000002/entitlement",
        params={"on": "2026-02-28"},
    )
    assert response.status_code == 200
    assert response.json()["subscription_status"] == "suspended"


@pytest.mark.rule("PLANS-004")
def test_change_plan_closes_prior_subscription(client):
    response = client.post(
        "/api/tenants/00000000-0000-0000-0000-000000000001/plan-change",
        json={
            "plan_id": "10000000-0000-0000-0000-000000000002",
            "effective_on": "2026-03-01",
        },
    )
    assert response.status_code == 200
    assert response.json()["subscriptions"][0]["ends_on"] == "2026-02-28"


@pytest.mark.rule("PLANS-005")
def test_change_plan_preserves_history(client):
    response = client.post(
        "/api/tenants/00000000-0000-0000-0000-000000000004/plan-change",
        json={
            "plan_id": "10000000-0000-0000-0000-000000000003",
            "effective_on": "2026-03-15",
        },
    )
    assert response.status_code == 200
    assert len(response.json()["subscriptions"]) == 2


def test_generated_seed_is_current():
    from scripts.generate_seed import generate

    seed_path = Path(__file__).parents[1] / "db" / "seed.sql"
    assert seed_path.read_text() == generate()
