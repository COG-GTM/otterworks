"""QA functional tests: legacy-portal bounded contexts over HTTP."""

from __future__ import annotations

import uuid

import pytest
from qa_billing_support import LEGACY_PORTAL_URL, service_client

pytestmark = pytest.mark.api_flow


@pytest.fixture(scope="module")
def portal():
    client = service_client(LEGACY_PORTAL_URL)
    yield client
    client.close()


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_portal_health_banner(portal):
    body = portal.get("/health").json()
    assert body["status"] == "UP"
    assert body["service"] == "legacy-portal"
    assert "on-prem" in body["banner"]


def test_portal_announcement_publish_flow(portal):
    title = uid("qa-ann")
    created = portal.post(
        "/api/announcements", json={"title": title, "body": "hello", "published": False}
    )
    assert created.status_code == 201, created.text
    announcement_id = created.json()["id"]
    assert title not in [a["title"] for a in portal.get("/api/announcements").json()]

    published = portal.post(f"/api/announcements/{announcement_id}/publish")
    assert published.status_code == 200
    listed = portal.get("/api/announcements").json()
    assert listed[0]["title"] == title


def test_portal_announcement_validation_and_404(portal):
    assert portal.post("/api/announcements", json={"title": "", "body": "b"}).status_code == 400
    assert portal.get("/api/announcements/987654321").status_code == 404


@pytest.mark.xfail(
    reason="QA-BILL-09: unpublished drafts are readable by id via GET /api/announcements/{id}",
    strict=True,
)
def test_portal_draft_not_readable_by_id(portal):
    created = portal.post(
        "/api/announcements", json={"title": uid("qa-draft"), "body": "b", "published": False}
    ).json()
    assert portal.get(f"/api/announcements/{created['id']}").status_code == 404


def test_portal_preferences_roundtrip(portal):
    user = uid("qa-user")
    assert portal.get(f"/api/preferences/{user}").json()["theme"] == "light"
    updated = portal.put(
        f"/api/preferences/{user}",
        json={"theme": "dark", "locale": "fr-FR", "emailNotifications": False},
    )
    assert updated.status_code == 200
    body = portal.get(f"/api/preferences/{user}").json()
    assert (body["theme"], body["locale"], body["emailNotifications"]) == ("dark", "fr-FR", False)


def test_portal_preferences_validation(portal):
    response = portal.put(f"/api/preferences/{uid('qa-user')}", json={"theme": ""})
    assert response.status_code == 400


def test_portal_feedback_flow(portal):
    user = uid("qa-fb")
    for rating in (1, 5):
        response = portal.post(
            "/api/feedback", json={"userId": user, "rating": rating, "message": "m"}
        )
        assert response.status_code == 201
    assert len(portal.get("/api/feedback", params={"userId": user}).json()) == 2
    average = portal.get("/api/feedback/average-rating").json()["averageRating"]
    assert 1 <= average <= 5


@pytest.mark.parametrize("rating", [0, 6])
def test_portal_feedback_rejects_bad_rating(portal, rating):
    response = portal.post(
        "/api/feedback", json={"userId": uid("qa-fb"), "rating": rating, "message": "m"}
    )
    assert response.status_code == 400
