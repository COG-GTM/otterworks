import pytest


pytestmark = pytest.mark.api_flow


def test_audit_event_query_reports_export_and_archive(api_client):
    user = api_client.register_user("audit-flow")
    resource_id = f"resource-{api_client.run_id}"

    create_response = api_client.client.post(
        "/api/v1/audit/events",
        headers=user.auth_headers,
        json={
            "userId": user.id,
            "action": "create",
            "resourceType": "document",
            "resourceId": resource_id,
            "details": {"source": "api-flow-test"},
        },
    )
    assert create_response.status_code == 201, create_response.text
    event = create_response.json()
    event_id = event["id"]

    get_response = api_client.client.get(f"/api/v1/audit/events/{event_id}", headers=user.auth_headers)
    assert get_response.status_code == 200, get_response.text

    query_response = api_client.client.get(
        "/api/v1/audit/events",
        headers=user.auth_headers,
        params={"user_id": user.id, "action": "create", "page": 1, "size": 10},
    )
    assert query_response.status_code == 200, query_response.text
    assert query_response.json()["total"] >= 1

    history_response = api_client.client.get(
        f"/api/v1/audit/resources/{resource_id}/history",
        headers=user.auth_headers,
    )
    assert history_response.status_code == 200, history_response.text

    user_report_response = api_client.client.get(
        f"/api/v1/audit/reports/user/{user.id}",
        headers=user.auth_headers,
        params={"period": "30d"},
    )
    assert user_report_response.status_code == 200, user_report_response.text

    compliance_response = api_client.client.get(
        "/api/v1/audit/reports/compliance",
        headers=user.auth_headers,
        params={"period": "30d"},
    )
    assert compliance_response.status_code == 200, compliance_response.text

    export_response = api_client.client.get(
        "/api/v1/audit/export",
        headers=user.auth_headers,
        params={"format": "json"},
    )
    assert export_response.status_code == 200, export_response.text

    invalid_export = api_client.client.get(
        "/api/v1/audit/export",
        headers=user.auth_headers,
        params={"format": "xml"},
    )
    assert invalid_export.status_code == 400

    archive_response = api_client.client.post("/api/v1/audit/archive", headers=user.auth_headers)
    assert archive_response.status_code == 200, archive_response.text


def test_analytics_event_ingestion_queries_and_export(api_client):
    user = api_client.register_user("analytics-flow")
    resource_id = f"analytics-resource-{api_client.run_id}"

    track_response = api_client.client.post(
        "/api/v1/analytics/events",
        headers=user.auth_headers,
        json={
            "eventType": "document_viewed",
            "userId": user.id,
            "resourceId": resource_id,
            "resourceType": "document",
            "metadata": {"source": "api-flow-test"},
        },
    )
    assert track_response.status_code in {200, 201, 202}, track_response.text

    activity_response = api_client.client.get(
        f"/api/v1/analytics/users/{user.id}/activity",
        headers=user.auth_headers,
    )
    assert activity_response.status_code == 200, activity_response.text
    assert activity_response.json()["userId"] == user.id

    document_stats_response = api_client.client.get(
        f"/api/v1/analytics/documents/{resource_id}/stats",
        headers=user.auth_headers,
    )
    assert document_stats_response.status_code == 200, document_stats_response.text

    storage_response = api_client.client.get(
        "/api/v1/analytics/storage",
        headers=user.auth_headers,
        params={"user_id": user.id},
    )
    assert storage_response.status_code == 200, storage_response.text

    own_storage_response = api_client.client.get("/api/v1/analytics/storage", headers=user.auth_headers)
    assert own_storage_response.status_code == 200, own_storage_response.text
    assert own_storage_response.json()["userId"] == user.id


def test_analytics_queries_are_scoped_to_the_caller(api_client):
    owner = api_client.register_user("analytics-owner")
    other = api_client.register_user("analytics-other")

    other_activity = api_client.client.get(
        f"/api/v1/analytics/users/{owner.id}/activity",
        headers=other.auth_headers,
    )
    assert other_activity.status_code == 403, other_activity.text

    other_storage = api_client.client.get(
        "/api/v1/analytics/storage",
        headers=other.auth_headers,
        params={"user_id": owner.id},
    )
    assert other_storage.status_code == 403, other_storage.text

    for path, params in (
        ("/api/v1/analytics/dashboard", {"period": "7d"}),
        ("/api/v1/analytics/top-content", {"type": "documents", "period": "7d", "limit": 5}),
        ("/api/v1/analytics/active-users", {"period": "daily"}),
        ("/api/v1/analytics/export", {"format": "csv", "period": "30d"}),
        ("/api/v1/analytics/export", {"format": "json", "period": "7d"}),
    ):
        response = api_client.client.get(path, headers=other.auth_headers, params=params)
        assert response.status_code == 403, f"{path}: {response.status_code} {response.text}"


def test_report_generation_lifecycle_and_gateway_route(api_client):
    user = api_client.register_user("report-flow")

    create_response = api_client.client.post(
        "/api/v1/reports",
        headers=user.auth_headers,
        json={
            "reportName": f"API Flow Report {api_client.run_id}",
            "category": "USAGE_ANALYTICS",
            "reportType": "CSV",
            "requestedBy": user.id,
            "dateFrom": api_client.iso_time(-7),
            "dateTo": api_client.iso_time(),
            "parameters": {"source": "api-flow-test"},
        },
    )
    api_client.assert_gateway_route_available(create_response, "/api/v1/reports")
    assert create_response.status_code == 202, create_response.text
    report = create_response.json()
    report_id = report["id"]
    api_client.created_reports.append(report_id)

    get_response = api_client.client.get(f"/api/v1/reports/{report_id}", headers=user.auth_headers)
    assert get_response.status_code == 200, get_response.text

    list_response = api_client.client.get(
        "/api/v1/reports",
        headers=user.auth_headers,
        params={"userId": user.id},
    )
    assert list_response.status_code == 200, list_response.text

    download_response = api_client.client.get(
        f"/api/v1/reports/{report_id}/download",
        headers=user.auth_headers,
    )
    assert download_response.status_code in {200, 202, 404, 409}, download_response.text

    delete_response = api_client.client.delete(f"/api/v1/reports/{report_id}", headers=user.auth_headers)
    assert delete_response.status_code == 204, delete_response.text
    api_client.created_reports.remove(report_id)

    invalid_report = api_client.client.post(
        "/api/v1/reports",
        headers=user.auth_headers,
        json={"category": "USAGE_ANALYTICS", "reportType": "CSV", "requestedBy": user.id},
    )
    assert invalid_report.status_code in {400, 422}
