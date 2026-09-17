"""Error, chaos and helper paths of the search API blueprint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.api.search as search_api
from app.models.search_result import SearchResponse


@pytest.fixture()
def search_service(app) -> MagicMock:
    """Replace the shared MeiliSearchService with a mock for the test app."""
    service = MagicMock()
    app.config["SEARCH_SERVICE"] = service
    return service


def _empty_response(query: str = "q") -> SearchResponse:
    return SearchResponse(results=[], total=0, page=1, page_size=20, query=query)


class TestRedisHelpers:
    """_get_redis is lazily created and cached; chaos lookups never raise."""

    def test_redis_client_is_created_once_and_reused(self, monkeypatch):
        monkeypatch.setattr(search_api, "_redis_client", None)
        monkeypatch.setenv("REDIS_HOST", "redis-host")
        monkeypatch.setenv("REDIS_PORT", "6380")

        with patch.object(search_api.redis_lib, "Redis") as redis_cls:
            first = search_api._get_redis()
            second = search_api._get_redis()

        redis_cls.assert_called_once_with(
            host="redis-host", port=6380, decode_responses=True, socket_timeout=1
        )
        assert first is second is redis_cls.return_value

    def test_chaos_flag_is_true_when_the_key_exists(self, monkeypatch):
        redis_client = MagicMock()
        redis_client.exists.return_value = 1
        monkeypatch.setattr(search_api, "_get_redis", lambda: redis_client)

        assert search_api._chaos_active("chaos:search-service:suggest_500") is True
        redis_client.exists.assert_called_once_with("chaos:search-service:suggest_500")

    def test_chaos_flag_is_false_when_redis_is_unreachable(self, monkeypatch):
        def boom():
            raise ConnectionError("redis down")

        monkeypatch.setattr(search_api, "_get_redis", boom)

        assert search_api._chaos_active("chaos:search-service:suggest_500") is False


class TestSearchEndpointErrors:
    """GET /api/v1/search/ validation and failure handling."""

    def test_invalid_size_returns_400(self, client):
        response = client.get("/api/v1/search/?q=report&size=huge")
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid page or size parameter"}

    def test_invalid_filter_returns_400(self, client, search_service):
        search_service.search.side_effect = ValueError("Invalid search filter: bad field")

        response = client.get("/api/v1/search/?q=report")

        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid search filter: bad field"}

    def test_backend_failure_returns_500(self, client, search_service):
        search_service.search.side_effect = RuntimeError("meilisearch down")

        response = client.get("/api/v1/search/?q=report")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Search failed"}

    def test_user_header_scopes_the_search_to_the_owner(self, client, search_service):
        search_service.search.return_value = _empty_response("report")

        response = client.get(
            "/api/v1/search/?q=report&type=document&page=2&size=5",
            headers={"X-User-ID": " user-1 "},
        )

        assert response.status_code == 200
        search_service.search.assert_called_once_with(
            query="report", doc_type="document", owner_id="user-1", page=2, page_size=5
        )

    def test_page_and_size_are_clamped_to_supported_bounds(self, client, search_service):
        search_service.search.return_value = _empty_response("report")

        client.get("/api/v1/search/?q=report&page=0&size=500")

        assert search_service.search.call_args.kwargs["page"] == 1
        assert search_service.search.call_args.kwargs["page_size"] == 100


class TestSuggestEndpoint:
    """GET /api/v1/search/suggest, including the injected chaos path."""

    def test_backend_failure_degrades_to_an_empty_suggestion_list(self, client, search_service):
        search_service.suggest.side_effect = RuntimeError("meilisearch down")

        response = client.get("/api/v1/search/suggest?q=rep")

        assert response.status_code == 200
        assert response.get_json() == {"suggestions": [], "query": "rep"}

    def test_chaos_path_sorts_suggestions_by_ranking_score(self, client, search_service, monkeypatch):
        monkeypatch.setattr(search_api, "_chaos_active", lambda key: True)
        search_service.suggest.return_value = [
            {"title": "low", "_rankingScore": 0.1},
            {"title": "high", "_rankingScore": 0.9},
        ]

        response = client.get("/api/v1/search/suggest?q=rep")

        assert response.status_code == 200
        assert [s["title"] for s in response.get_json()["suggestions"]] == ["high", "low"]

    def test_chaos_path_raises_when_ranking_scores_are_absent(
        self, client, search_service, monkeypatch
    ):
        """Planted chaos bug: _rankingScore is never returned by MeiliSearch here."""
        monkeypatch.setattr(search_api, "_chaos_active", lambda key: True)
        search_service.suggest.return_value = []

        with pytest.raises(KeyError, match="_rankingScore"):
            client.get("/api/v1/search/suggest?q=rep")


class TestAdvancedSearchErrors:
    """POST /api/v1/search/advanced validation and failure handling."""

    def test_invalid_page_returns_400(self, client):
        response = client.post("/api/v1/search/advanced", json={"page": "first"})

        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid page or size parameter"}

    def test_backend_failure_returns_500(self, client, search_service):
        search_service.advanced_search.side_effect = RuntimeError("meilisearch down")

        response = client.post("/api/v1/search/advanced", json={"q": "report"})

        assert response.status_code == 500
        assert response.get_json() == {"error": "Advanced search failed"}

    def test_filters_and_owner_scope_are_forwarded(self, client, search_service):
        search_service.advanced_search.return_value = _empty_response("report")

        response = client.post(
            "/api/v1/search/advanced",
            json={
                "q": "report",
                "type": "file",
                "tags": ["finance"],
                "date_from": "2026-01-01",
                "date_to": "2026-02-01",
                "page": 3,
                "size": 200,
            },
            headers={"X-User-ID": "user-7"},
        )

        assert response.status_code == 200
        search_service.advanced_search.assert_called_once_with(
            query="report",
            doc_type="file",
            owner_id="user-7",
            tags=["finance"],
            date_from="2026-01-01",
            date_to="2026-02-01",
            page=3,
            page_size=100,
        )


class TestAnalyticsEndpointErrors:
    """GET /api/v1/search/analytics failure handling."""

    def test_failure_returns_500(self, client, monkeypatch):
        def boom():
            raise RuntimeError("analytics store unavailable")

        monkeypatch.setattr(search_api, "get_search_analytics", boom)

        response = client.get("/api/v1/search/analytics")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to retrieve analytics"}
