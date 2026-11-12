"""Tests for health and metrics endpoints."""

from __future__ import annotations

import pytest


class TestHealthEndpoint:
    """Tests for GET /health (liveness)."""

    def test_health_returns_200(self, client):
        """Liveness always returns 200 without contacting dependencies."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "alive"
        assert data["service"] == "search-service"


class TestReadinessEndpoint:
    """Tests for GET /health/ready."""

    def test_ready_when_meilisearch_connected(self, client, mock_meilisearch_client):
        """Readiness returns 200 when MeiliSearch is reachable."""
        mock_meilisearch_client.health.return_value = {"status": "available"}
        response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.get_json()
        assert data["ready"] is True

    def test_not_ready_when_meilisearch_disconnected(self, client, mock_meilisearch_client):
        """Readiness returns 503 when MeiliSearch is unreachable."""
        mock_meilisearch_client.health.side_effect = Exception("unreachable")
        response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.get_json()
        assert data["ready"] is False


class TestMetricsEndpoint:
    """Tests for GET /metrics."""

    def test_metrics_returns_prometheus_format(self, client):
        """Metrics endpoint returns Prometheus text format."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert b"search_service" in response.data


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
class TestHealthEndpointMethods:
    """Health and metrics endpoints only accept GET (and implicit HEAD/OPTIONS)."""

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_non_get_methods_rejected(self, client, path, method):
        response = getattr(client, method)(path)
        assert response.status_code == 405
        assert "GET" in response.headers["Allow"]

    def test_head_allowed(self, client, path):
        response = client.head(path)
        assert response.status_code in (200, 503)
