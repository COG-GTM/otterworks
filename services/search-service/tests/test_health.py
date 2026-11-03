"""Tests for health and metrics endpoints."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.config import AuthConfig


class TestHealthEndpoint:
    """Tests for GET /health (liveness)."""

    def test_health_returns_200(self, client):
        """Liveness always returns 200 without contacting dependencies."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "alive"
        assert data["service"] == "search-service"

    def test_health_alive_when_meilisearch_disconnected(self, client, mock_meilisearch_client):
        """Liveness must not fail (and restart the pod) when MeiliSearch is down."""
        mock_meilisearch_client.health.side_effect = Exception("unreachable")
        response = client.get("/health")
        assert response.status_code == 200
        mock_meilisearch_client.health.assert_not_called()


@pytest.mark.parametrize("path", ["/ready", "/health/ready"])
class TestReadinessEndpoint:
    """Tests for GET /ready and its /health/ready alias."""

    def test_ready_when_meilisearch_connected(self, client, mock_meilisearch_client, path):
        """Readiness returns 200 when MeiliSearch is reachable."""
        mock_meilisearch_client.health.return_value = {"status": "available"}
        response = client.get(path)
        assert response.status_code == 200
        data = response.get_json()
        assert data["ready"] is True
        mock_meilisearch_client.health.assert_called()

    def test_not_ready_when_meilisearch_disconnected(self, client, mock_meilisearch_client, path):
        """Readiness returns 503 when MeiliSearch is unreachable."""
        mock_meilisearch_client.health.side_effect = Exception("unreachable")
        response = client.get(path)
        assert response.status_code == 503
        data = response.get_json()
        assert data["ready"] is False
        assert data["reason"] == "meilisearch_unavailable"


class TestProbesArePublic:
    """Kubelet probes carry no credentials, so probe paths must bypass auth."""

    @pytest.fixture()
    def app_config(self, app_config):
        return replace(app_config, auth=AuthConfig(service_token="secret", require_auth=True))

    @pytest.mark.parametrize("path", ["/health", "/ready", "/health/ready"])
    def test_probe_paths_skip_auth(self, client, path):
        assert client.get(path).status_code == 200

    def test_api_still_requires_auth(self, client):
        assert client.get("/api/v1/search/?q=x").status_code == 401


class TestMetricsEndpoint:
    """Tests for GET /metrics."""

    def test_metrics_returns_prometheus_format(self, client):
        """Metrics endpoint returns Prometheus text format."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert b"search_service" in response.data
