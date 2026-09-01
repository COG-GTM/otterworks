"""Tests for readiness when the search backend is not wired up."""

from __future__ import annotations


class TestReadinessWithoutSearchService:
    """The readiness probe must fail closed."""

    def test_missing_search_service_reports_not_ready(self, app):
        """With no MeiliSearch service configured the probe returns 503."""
        app.config.pop("SEARCH_SERVICE")

        response = app.test_client().get("/health/ready")

        assert response.status_code == 503
        assert response.get_json() == {"ready": False, "reason": "meilisearch_unavailable"}

    def test_liveness_is_unaffected_by_a_missing_backend(self, app):
        """Liveness stays green so the pod is not restarted for a dependency outage."""
        app.config.pop("SEARCH_SERVICE")

        response = app.test_client().get("/health")

        assert response.status_code == 200
        assert response.get_json()["status"] == "alive"
