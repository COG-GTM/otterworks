"""QA audit of analytics-service (/api/v1/analytics) and report-service (/api/v1/reports).

Findings referenced in xfail reasons are documented in docs/qa/analytics-report.md.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.api_flow

REPORT_SERVICE_URL = os.getenv("OTTERWORKS_REPORT_SERVICE_URL", "http://localhost:8091")
TERMINAL = {"COMPLETED", "FAILED"}


def _uid(prefix: str) -> str:
    return f"qa-{prefix}-{uuid.uuid4().hex[:10]}"


def _track(
    api_client,
    user,
    event_type: str,
    user_id: str,
    resource_id: str,
    resource_type: str = "document",
    **meta,
):
    payload = {
        "eventType": event_type,
        "userId": user_id,
        "resourceId": resource_id,
        "resourceType": resource_type,
    }
    if meta:
        payload["metadata"] = {k: str(v) for k, v in meta.items()}
    return api_client.client.post(
        "/api/v1/analytics/events", headers=user.auth_headers, json=payload
    )


def _create_report(api_client, user, **overrides) -> httpx.Response:
    payload = {
        "reportName": f"QA report {api_client.run_id}",
        "category": "STORAGE_SUMMARY",
        "reportType": "CSV",
        "requestedBy": user.id,
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    response = api_client.client.post(
        "/api/v1/reports", headers=user.auth_headers, json=payload
    )
    if response.status_code == 202:
        api_client.created_reports.append(response.json()["id"])
    return response


def _wait_terminal(api_client, user, report_id: int) -> dict:
    return api_client.poll_until(
        lambda: api_client.client.get(
            f"/api/v1/reports/{report_id}", headers=user.auth_headers
        ).json(),
        lambda body: body.get("status") in TERMINAL,
        description=f"report {report_id} to finish",
    )


# --------------------------------------------------------------------------- analytics


def test_analytics_ingested_events_drive_all_aggregates(api_client):
    user = api_client.register_user("qa-analytics")
    actor, doc, other_doc = _uid("actor"), _uid("doc"), _uid("doc")

    for event_type, resource in [
        ("document.created", doc),
        ("document.viewed", doc),
        ("document.viewed", doc),
        ("document.edited", doc),
        ("document.viewed", other_doc),
    ]:
        r = _track(api_client, user, event_type, actor, resource, title="QA Doc")
        assert r.status_code == 202, r.text
        assert r.json()["status"] == "accepted" and r.json()["eventId"]
    r = _track(api_client, user, "storage.allocated", actor, doc, bytes=4096)
    assert r.status_code == 202, r.text

    activity = api_client.client.get(
        f"/api/v1/analytics/users/{actor}/activity", headers=user.auth_headers
    )
    assert activity.status_code == 200, activity.text
    body = activity.json()
    assert body["totalEvents"] == 6
    assert body["documentsCreated"] == 1
    assert body["documentsViewed"] == 3
    assert body["documentsEdited"] == 1
    assert body["lastActiveAt"]

    stats = api_client.client.get(
        f"/api/v1/analytics/documents/{doc}/stats", headers=user.auth_headers
    ).json()
    assert (stats["views"], stats["edits"], stats["uniqueViewers"]) == (2, 1, 1)

    storage = api_client.client.get(
        "/api/v1/analytics/storage",
        params={"user_id": actor},
        headers=user.auth_headers,
    )
    assert storage.status_code == 200 and storage.json()["totalStorageBytes"] == 4096

    dashboard = api_client.client.get(
        "/api/v1/analytics/dashboard",
        params={"period": "7d"},
        headers=user.auth_headers,
    )
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["period"] == "7d"
    assert dashboard.json()["totalEvents"] >= 6
    assert dashboard.json()["documentsCreated"] >= 1

    active = api_client.client.get(
        "/api/v1/analytics/active-users",
        params={"period": "daily"},
        headers=user.auth_headers,
    )
    assert actor in {u["userId"] for u in active.json()["users"]}

    top = api_client.client.get(
        "/api/v1/analytics/top-content",
        params={"type": "documents", "period": "7d", "limit": 500},
        headers=user.auth_headers,
    )
    assert top.status_code == 200
    assert doc in {item["resourceId"] for item in top.json()["items"]}

    csv_export = api_client.client.get(
        "/api/v1/analytics/export", params={"format": "csv"}, headers=user.auth_headers
    )
    assert csv_export.status_code == 200
    assert csv_export.text.startswith(
        "event_id,event_type,user_id,resource_id,resource_type,timestamp"
    )
    assert doc in csv_export.text

    json_export = api_client.client.get(
        "/api/v1/analytics/export", params={"period": "30d"}, headers=user.auth_headers
    )
    assert json_export.status_code == 200
    assert json_export.json()["format"] == "json"
    assert json_export.json()["recordCount"] == len(json_export.json()["data"])


def test_analytics_requires_authentication_at_gateway(api_client):
    response = api_client.client.get("/api/v1/analytics/dashboard")
    assert response.status_code == 401, response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"eventType": "document.created"},
        {"userId": "u", "resourceId": "r", "resourceType": "document"},
        "not-json",
    ],
    ids=["missing-ids", "missing-type", "malformed"],
)
def test_analytics_event_validation_rejects_bad_bodies(api_client, payload):
    user = api_client.register_user("qa-analytics-val")
    if isinstance(payload, str):
        r = api_client.client.post(
            "/api/v1/analytics/events",
            headers={**user.auth_headers, "Content-Type": "application/json"},
            content=payload,
        )
    else:
        r = api_client.client.post(
            "/api/v1/analytics/events", headers=user.auth_headers, json=payload
        )
    assert r.status_code == 400, r.text


def test_analytics_top_content_rejects_non_numeric_limit(api_client):
    user = api_client.register_user("qa-analytics-limit")
    r = api_client.client.get(
        "/api/v1/analytics/top-content",
        params={"limit": "lots"},
        headers=user.auth_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.xfail(
    reason="ANL-1: unknown eventType accepted (202) instead of 400", strict=True
)
def test_analytics_rejects_unknown_event_type(api_client):
    user = api_client.register_user("qa-analytics-type")
    r = _track(api_client, user, "made.up_event", user.id, _uid("doc"))
    assert r.status_code == 400, r.text


@pytest.mark.xfail(
    reason="ANL-3: unknown period silently treated as 7d and echoed back", strict=True
)
def test_analytics_rejects_unknown_period(api_client):
    user = api_client.register_user("qa-analytics-period")
    r = api_client.client.get(
        "/api/v1/analytics/dashboard",
        params={"period": "forever"},
        headers=user.auth_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.xfail(
    reason="ANL-6: analytics trusts body userId and exposes any user's activity (no ownership check)",
    strict=True,
)
def test_analytics_enforces_user_ownership(api_client):
    alice = api_client.register_user("qa-analytics-alice")
    mallory = api_client.register_user("qa-analytics-mallory")
    spoof = _track(api_client, mallory, "document.created", alice.id, _uid("doc"))
    assert spoof.status_code in {400, 403}, (
        "event attributed to another user was accepted"
    )
    peek = api_client.client.get(
        f"/api/v1/analytics/users/{alice.id}/activity", headers=mallory.auth_headers
    )
    assert peek.status_code in {403, 404}, peek.text


@pytest.mark.xfail(
    reason="ANL-7: document/file activity never reaches analytics locally (EventProcessor SQS queue not provisioned; no direct publisher)",
    strict=True,
)
def test_document_activity_reaches_analytics(api_client):
    user = api_client.register_user("qa-analytics-flow")
    api_client.create_document(
        user, f"QA analytics doc {api_client.run_id}", "hello analytics"
    )
    api_client.poll_until(
        lambda: api_client.client.get(
            f"/api/v1/analytics/users/{user.id}/activity", headers=user.auth_headers
        ).json(),
        lambda body: body.get("documentsCreated", 0) >= 1,
        timeout_seconds=15,
        description="document.created event to reach analytics",
    )


# --------------------------------------------------------------------------- reports


def test_report_generate_download_list_delete_lifecycle(api_client):
    user = api_client.register_user("qa-report")
    created = _create_report(api_client, user, reportName="QA Storage Summary")
    assert created.status_code == 202, created.text
    report = created.json()
    assert report["status"] == "PENDING"
    assert report["requestedBy"] == user.id
    assert report["dateFrom"] and report["dateTo"]

    done = _wait_terminal(api_client, user, report["id"])
    assert done["status"] == "COMPLETED", done
    assert done["rowCount"] > 0
    assert done["fileSizeBytes"] > 0

    download = api_client.client.get(
        f"/api/v1/reports/{report['id']}/download", headers=user.auth_headers
    )
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("text/csv")
    assert "attachment" in download.headers["content-disposition"]
    assert len(download.content) == done["fileSizeBytes"]
    assert download.text.splitlines()[0]

    listing = api_client.client.get(
        "/api/v1/reports", params={"userId": user.id}, headers=user.auth_headers
    ).json()
    assert report["id"] in {r["id"] for r in listing["reports"]}
    assert listing["total"] == len(listing["reports"])

    deleted = api_client.client.delete(
        f"/api/v1/reports/{report['id']}", headers=user.auth_headers
    )
    assert deleted.status_code == 204
    api_client.created_reports.remove(report["id"])
    assert (
        api_client.client.get(
            f"/api/v1/reports/{report['id']}", headers=user.auth_headers
        ).status_code
        == 404
    )
    assert (
        api_client.client.get(
            f"/api/v1/reports/{report['id']}/download", headers=user.auth_headers
        ).status_code
        == 404
    )


@pytest.mark.parametrize("report_type", ["PDF", "EXCEL"])
def test_report_other_formats_download(api_client, report_type):
    user = api_client.register_user("qa-report-fmt")
    created = _create_report(
        api_client, user, reportType=report_type, category="USER_ACTIVITY"
    )
    assert created.status_code == 202, created.text
    done = _wait_terminal(api_client, user, created.json()["id"])
    assert done["status"] == "COMPLETED", done
    download = api_client.client.get(
        f"/api/v1/reports/{done['id']}/download", headers=user.auth_headers
    )
    assert download.status_code == 200
    magic = {"PDF": b"%PDF", "EXCEL": b"PK"}[report_type]
    assert download.content.startswith(magic)


@pytest.mark.parametrize(
    "overrides",
    [
        {"reportName": None},
        {"requestedBy": ""},
        {"category": "NOT_A_CATEGORY"},
        {"reportType": "DOCX"},
        {"category": None},
    ],
    ids=["no-name", "blank-requester", "bad-category", "bad-type", "no-category"],
)
def test_report_request_validation(api_client, overrides):
    user = api_client.register_user("qa-report-val")
    r = _create_report(api_client, user, **overrides)
    assert r.status_code == 400, r.text


def test_report_unknown_ids(api_client):
    user = api_client.register_user("qa-report-404")
    for method, path in [
        ("GET", "/api/v1/reports/999999999"),
        ("GET", "/api/v1/reports/999999999/download"),
        ("DELETE", "/api/v1/reports/999999999"),
    ]:
        assert (
            api_client.client.request(
                method, path, headers=user.auth_headers
            ).status_code
            == 404
        ), path


def test_reports_require_authentication_at_gateway(api_client):
    assert api_client.client.get("/api/v1/reports").status_code == 401


@pytest.mark.xfail(
    reason="RPT-1: USAGE_ANALYTICS reports always FAIL (GET /api/v1/analytics/events not served; fallback unreachable)",
    strict=True,
)
def test_usage_analytics_report_completes(api_client):
    user = api_client.register_user("qa-report-usage")
    created = _create_report(api_client, user, category="USAGE_ANALYTICS")
    assert created.status_code == 202, created.text
    done = _wait_terminal(api_client, user, created.json()["id"])
    assert done["status"] == "COMPLETED", done


@pytest.mark.xfail(
    reason="RPT-2: inverted date range (dateFrom > dateTo) accepted", strict=True
)
def test_report_rejects_inverted_date_range(api_client):
    user = api_client.register_user("qa-report-range")
    r = _create_report(
        api_client,
        user,
        dateFrom=api_client.iso_time(0),
        dateTo=api_client.iso_time(-30),
    )
    assert r.status_code == 400, r.text


@pytest.mark.xfail(
    reason="RPT-3: report-service permits /api/v1/reports/** unauthenticated on its own port",
    strict=True,
)
def test_report_service_port_requires_authentication():
    r = httpx.get(f"{REPORT_SERVICE_URL}/api/v1/reports", timeout=5)
    assert r.status_code == 401, r.status_code


@pytest.mark.xfail(
    reason="RPT-6: no ownership checks; any user can read/download/delete another user's report",
    strict=True,
)
def test_report_ownership_is_enforced(api_client):
    alice = api_client.register_user("qa-report-alice")
    mallory = api_client.register_user("qa-report-mallory")
    report = _create_report(api_client, alice).json()
    _wait_terminal(api_client, alice, report["id"])
    assert api_client.client.get(
        f"/api/v1/reports/{report['id']}", headers=mallory.auth_headers
    ).status_code in {403, 404}
    listing = api_client.client.get(
        "/api/v1/reports", params={"userId": alice.id}, headers=mallory.auth_headers
    )
    assert listing.status_code in {403, 404} or not listing.json()["reports"]


@pytest.mark.xfail(
    reason="RPT-4: auth-service rejects report-service (403) so reports silently contain fabricated sample users",
    strict=True,
)
def test_completed_user_report_contains_real_users(api_client):
    user = api_client.register_user("qa-report-real")
    created = _create_report(api_client, user, category="USER_ACTIVITY")
    assert created.status_code == 202, created.text
    done = _wait_terminal(api_client, user, created.json()["id"])
    assert done["status"] == "COMPLETED", done
    csv_text = api_client.client.get(
        f"/api/v1/reports/{done['id']}/download", headers=user.auth_headers
    ).text
    assert "@otterworks.example.com" not in csv_text, (
        "report rows are generateSampleUserActivityData placeholders"
    )
