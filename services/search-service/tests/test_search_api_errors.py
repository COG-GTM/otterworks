"""Tests for the error, chaos and Redis paths of the search API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.api.search as search_api

CHAOS_KEY = "chaos:search-service:suggest_500"


@pytest.fixture()
def search_service(app) -> MagicMock:
    """Replace the app's MeiliSearchService with a mock."""
    service = MagicMock()
    app.config["SEARCH_SERVICE"] = service
    return service


class TestRedisChaosFlag:
    """Tests for the lazily-created Redis client behind the chaos flags."""

    def test_client_is_created_once_and_reused(self, monkeypatch):
        """_get_redis caches the client across calls."""
        monkeypatch.setattr(search_api, "_redis_client", None)
        monkeypatch.setenv("REDIS_HOST", "redis.test")
        monkeypatch.setenv("REDIS_PORT", "6380")
        redis_cls = MagicMock()
        redis_cls.return_value.exists.return_value = 1

        with patch.object(search_api.redis_lib, "Redis", redis_cls):
            assert search_api._chaos_active(CHAOS_KEY) is True
            assert search_api._chaos_active(CHAOS_KEY) is True

        redis_cls.assert_called_once_with(
            host="redis.test", port=6380, decode_responses=True, socket_timeout=1
        )

    def test_missing_flag_is_inactive(self, monkeypatch):
        monkeypatch.setattr(search_api, "_redis_client", None)
        redis_cls = MagicMock()
        redis_cls.return_value.exists.return_value = 0

        with patch.object(search_api.redis_lib, "Redis", redis_cls):
            assert search_api._chaos_active(CHAOS_KEY) is False

    def test_unreachable_redis_is_inactive(self, monkeypatch):
        """A Redis outage must not fail the request; chaos is simply off."""
        monkeypatch.setattr(search_api, "_redis_client", None)
        redis_cls = MagicMock()
        redis_cls.return_value.exists.side_effect = ConnectionError("redis down")

        with patch.object(search_api.redis_lib, "Redis", redis_cls):
            assert search_api._chaos_active(CHAOS_KEY) is False


class TestSearchErrors:
    """Tests for GET /api/v1/search/."""

    def test_invalid_page_parameter_returns_400(self, client):
        response = client.get("/api/v1/search/?q=hello&page=abc")

        assert response.status_code == 400
        assert response.get_json()["error"] == "Invalid page or size parameter"

    def test_invalid_size_parameter_returns_400(self, client):
        assert client.get("/api/v1/search/?q=hello&size=big").status_code == 400

    def test_invalid_filter_returns_400(self, client, search_service):
        """A ValueError from the search layer surfaces as a client error."""
        search_service.search.side_effect = ValueError("Invalid search filter: bad")

        response = client.get("/api/v1/search/?q=hello")

        assert response.status_code == 400
        assert response.get_json()["error"] == "Invalid search filter: bad"

    def test_backend_failure_returns_500(self, client, search_service):
        search_service.search.side_effect = RuntimeError("meilisearch down")

        response = client.get("/api/v1/search/?q=hello")

        assert response.status_code == 500
        assert response.get_json()["error"] == "Search failed"


class TestSuggestErrors:
    """Tests for GET /api/v1/search/suggest."""

    def test_backend_failure_degrades_to_empty_suggestions(self, client, search_service):
        """Autocomplete is best-effort: failures return 200 with no suggestions."""
        search_service.suggest.side_effect = RuntimeError("meilisearch down")

        response = client.get("/api/v1/search/suggest?q=inv")

        assert response.status_code == 200
        assert response.get_json() == {"suggestions": [], "query": "inv"}

    def test_chaos_flag_ranks_suggestions_by_score(self, client, search_service):
        """With the chaos flag on, hits carrying _rankingScore are sorted by it."""
        search_service.suggest.return_value = [
            {"title": "low", "_rankingScore": 0.1},
            {"title": "high", "_rankingScore": 0.9},
        ]

        with patch("app.api.search._chaos_active", return_value=True):
            response = client.get("/api/v1/search/suggest?q=inv")

        assert response.status_code == 200
        assert [s["title"] for s in response.get_json()["suggestions"]] == ["high", "low"]

    def test_chaos_flag_crashes_when_ranking_score_is_absent(self, client, search_service):
        """Planted chaos bug: the enrichment path assumes _rankingScore exists."""
        search_service.suggest.return_value = []

        with patch("app.api.search._chaos_active", return_value=True):
            with pytest.raises(KeyError, match="_rankingScore"):
                client.get("/api/v1/search/suggest?q=inv")


class TestAdvancedSearchErrors:
    """Tests for POST /api/v1/search/advanced."""

    @pytest.mark.parametrize("body", [{"page": "abc"}, {"size": None}])
    def test_invalid_pagination_returns_400(self, client, body):
        response = client.post("/api/v1/search/advanced", json=body)

        assert response.status_code == 400
        assert response.get_json()["error"] == "Invalid page or size parameter"

    def test_backend_failure_returns_500(self, client, search_service):
        search_service.advanced_search.side_effect = RuntimeError("meilisearch down")

        response = client.post("/api/v1/search/advanced", json={"q": "hello"})

        assert response.status_code == 500
        assert response.get_json()["error"] == "Advanced search failed"

    def test_filters_and_identity_are_forwarded_to_the_service(self, client, search_service):
        """Body filters plus the gateway identity reach the search layer."""
        search_service.advanced_search.return_value = MagicMock(
            total=0, to_dict=lambda: {"results": [], "total": 0}
        )

        response = client.post(
            "/api/v1/search/advanced",
            json={
                "q": "budget",
                "type": "document",
                "tags": ["finance"],
                "date_from": "2026-01-01",
                "date_to": "2026-02-01",
                "page": 2,
                "size": 5,
            },
            headers={"X-User-ID": "user-1"},
        )

        assert response.status_code == 200
        search_service.advanced_search.assert_called_once_with(
            query="budget",
            doc_type="document",
            owner_id="user-1",
            tags=["finance"],
            date_from="2026-01-01",
            date_to="2026-02-01",
            page=2,
            page_size=5,
        )


class TestAnalyticsErrors:
    """Tests for GET /api/v1/search/analytics."""

    def test_analytics_failure_returns_500(self, client):
        with patch(
            "app.api.search.get_search_analytics", side_effect=RuntimeError("boom")
        ):
            response = client.get("/api/v1/search/analytics")

        assert response.status_code == 500
        assert response.get_json()["error"] == "Failed to retrieve analytics"
