"""Edge cases for the health probes."""

from __future__ import annotations


class TestReadinessWithoutSearchService:
    """Readiness must not assume the search service was wired up."""

    def test_missing_search_service_is_not_ready(self, app):
        app.config.pop("SEARCH_SERVICE")

        response = app.test_client().get("/health/ready")

        assert response.status_code == 503
        assert response.get_json() == {
            "ready": False,
            "reason": "meilisearch_unavailable",
        }
