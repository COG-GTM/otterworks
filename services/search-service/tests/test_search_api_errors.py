"""Tests for error paths, chaos behaviour and helpers in the search API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api import search as search_module


@pytest.fixture()
def service(app) -> MagicMock:
    """Replace the app's MeiliSearch service with a mock."""
    mock = MagicMock()
    original = app.config["SEARCH_SERVICE"]
    app.config["SEARCH_SERVICE"] = mock
    yield mock
    app.config["SEARCH_SERVICE"] = original


class TestRedisHelpers:
    """Tests for the lazily-created Redis client and chaos flag lookup."""

    def test_redis_client_is_created_once_from_env(self, monkeypatch):
        """The client is built from REDIS_HOST/REDIS_PORT and then reused."""
        monkeypatch.setattr(search_module, "_redis_client", None)
        monkeypatch.setenv("REDIS_HOST", "redis.internal")
        monkeypatch.setenv("REDIS_PORT", "6380")
        redis_cls = MagicMock()

        with patch.object(search_module.redis_lib, "Redis", redis_cls):
            first = search_module._get_redis()
            second = search_module._get_redis()

        redis_cls.assert_called_once_with(
            host="redis.internal", port=6380, decode_responses=True, socket_timeout=1
        )
        assert first is second

    def test_chaos_flag_is_active_when_the_key_exists(self, monkeypatch):
        """A key present in Redis activates the flag."""
        redis = MagicMock()
        redis.exists.return_value = 1
        monkeypatch.setattr(search_module, "_get_redis", lambda: redis)

        assert search_module._chaos_active("chaos:search-service:suggest_500") is True
        redis.exists.assert_called_once_with("chaos:search-service:suggest_500")

    def test_chaos_flag_is_inactive_when_the_key_is_missing(self, monkeypatch):
        """An absent key leaves the flag off."""
        redis = MagicMock()
        redis.exists.return_value = 0
        monkeypatch.setattr(search_module, "_get_redis", lambda: redis)

        assert search_module._chaos_active("chaos:search-service:suggest_500") is False

    def test_chaos_flag_defaults_to_inactive_when_redis_is_down(self, monkeypatch):
        """A Redis outage must not enable chaos or raise."""
        redis = MagicMock()
        redis.exists.side_effect = ConnectionError("redis unreachable")
        monkeypatch.setattr(search_module, "_get_redis", lambda: redis)

        assert search_module._chaos_active("chaos:search-service:suggest_500") is False


class TestSearchEndpointErrors:
    """Failure modes of GET /api/v1/search/."""

    @pytest.mark.parametrize("query_string", ["q=test&page=abc", "q=test&size=xyz"])
    def test_non_numeric_pagination_returns_400(self, client, query_string):
        """Unparseable page/size values are rejected."""
        response = client.get(f"/api/v1/search/?{query_string}")
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid page or size parameter"}

    def test_invalid_filter_returns_400(self, client, service):
        """A ValueError (bad MeiliSearch filter) is a client error."""
        service.search.side_effect = ValueError("Invalid search filter: bad filter")

        response = client.get("/api/v1/search/?q=test")

        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid search filter: bad filter"}

    def test_backend_failure_returns_500(self, client, service):
        """An unexpected MeiliSearch error is masked behind a generic 500."""
        service.search.side_effect = RuntimeError("meilisearch down")

        response = client.get("/api/v1/search/?q=test")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Search failed"}

    def test_pagination_and_user_scope_are_forwarded_to_the_service(self, client, service):
        """Page/size are clamped and the gateway identity scopes the query."""
        service.search.return_value = MagicMock(
            total=0, to_dict=lambda: {"results": [], "total": 0}
        )

        response = client.get(
            "/api/v1/search/?q=test&page=0&size=500&type=file",
            headers={"X-User-ID": " user-7 "},
        )

        assert response.status_code == 200
        service.search.assert_called_once_with(
            query="test", doc_type="file", owner_id="user-7", page=1, page_size=100
        )


class TestSuggestEndpoint:
    """Behaviour of GET /api/v1/search/suggest."""

    @pytest.mark.parametrize("prefix", ["", "a"])
    def test_short_prefix_short_circuits_with_empty_suggestions(self, client, service, prefix):
        """Fewer than two characters never reaches MeiliSearch."""
        response = client.get(f"/api/v1/search/suggest?q={prefix}")

        assert response.status_code == 200
        assert response.get_json() == {"suggestions": [], "query": prefix}
        service.suggest.assert_not_called()

    def test_backend_failure_degrades_to_empty_suggestions(self, client, service, monkeypatch):
        """Autocomplete failures are swallowed so typing never errors."""
        monkeypatch.setattr(search_module, "_chaos_active", lambda key: False)
        service.suggest.side_effect = RuntimeError("meilisearch down")

        response = client.get("/api/v1/search/suggest?q=quar")

        assert response.status_code == 200
        assert response.get_json() == {"suggestions": [], "query": "quar"}

    def test_chaos_flag_sorts_suggestions_by_ranking_score(self, client, service, monkeypatch):
        """With the chaos flag on, scored hits are returned best-first."""
        monkeypatch.setattr(search_module, "_chaos_active", lambda key: True)
        service.suggest.return_value = [
            {"title": "low", "_rankingScore": 0.1},
            {"title": "high", "_rankingScore": 0.9},
        ]

        response = client.get("/api/v1/search/suggest?q=quar")

        assert response.status_code == 200
        assert [s["title"] for s in response.get_json()["suggestions"]] == ["high", "low"]

    def test_chaos_flag_crashes_on_unscored_suggestions(self, client, service, monkeypatch):
        """Planted chaos: without _rankingScore the handler raises KeyError.

        MeiliSearch only returns ``_rankingScore`` when it is explicitly
        requested, so the enrichment path blows up. This is the golden app's
        deliberate ``suggest_500`` scenario and is asserted, not fixed.
        """
        monkeypatch.setattr(search_module, "_chaos_active", lambda key: True)
        service.suggest.return_value = []

        with pytest.raises(KeyError, match="_rankingScore"):
            client.get("/api/v1/search/suggest?q=quar")


class TestAdvancedSearchEndpoint:
    """Behaviour of POST /api/v1/search/advanced."""

    def test_filters_are_forwarded_to_the_service(self, client, service):
        """Every documented filter reaches advanced_search, scoped to the user."""
        service.advanced_search.return_value = MagicMock(
            total=0, to_dict=lambda: {"results": [], "total": 0}
        )

        response = client.post(
            "/api/v1/search/advanced",
            json={
                "q": "budget",
                "type": "document",
                "tags": ["finance"],
                "date_from": "2026-01-01",
                "date_to": "2026-12-31",
                "page": 2,
                "size": 5,
            },
            headers={"X-User-ID": "user-7"},
        )

        assert response.status_code == 200
        service.advanced_search.assert_called_once_with(
            query="budget",
            doc_type="document",
            owner_id="user-7",
            tags=["finance"],
            date_from="2026-01-01",
            date_to="2026-12-31",
            page=2,
            page_size=5,
        )

    def test_empty_body_searches_everything(self, client, service):
        """An empty request body falls back to defaults rather than erroring."""
        service.advanced_search.return_value = MagicMock(
            total=0, to_dict=lambda: {"results": [], "total": 0}
        )

        response = client.post("/api/v1/search/advanced", json={})

        assert response.status_code == 200
        assert service.advanced_search.call_args.kwargs["page"] == 1
        assert service.advanced_search.call_args.kwargs["page_size"] == 20

    def test_non_numeric_pagination_returns_400(self, client, service):
        """Unparseable page/size values are rejected before searching."""
        response = client.post("/api/v1/search/advanced", json={"q": "x", "page": "abc"})

        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid page or size parameter"}
        service.advanced_search.assert_not_called()

    def test_backend_failure_returns_500(self, client, service):
        """An unexpected MeiliSearch error is masked behind a generic 500."""
        service.advanced_search.side_effect = RuntimeError("meilisearch down")

        response = client.post("/api/v1/search/advanced", json={"q": "budget"})

        assert response.status_code == 500
        assert response.get_json() == {"error": "Advanced search failed"}


class TestAnalyticsEndpoint:
    """Behaviour of GET /api/v1/search/analytics."""

    def test_analytics_are_returned(self, client):
        """Recorded searches are summarised for the dashboard."""
        client.get("/api/v1/search/?q=analytics-probe")

        response = client.get("/api/v1/search/analytics")

        assert response.status_code == 200
        body = response.get_json()
        assert body["total_searches"] >= 1
        assert "popular_queries" in body
        assert "zero_result_queries" in body

    def test_analytics_failure_returns_500(self, client):
        """A failure while aggregating analytics is reported as a server error."""
        with patch.object(
            search_module, "get_search_analytics", side_effect=RuntimeError("boom")
        ):
            response = client.get("/api/v1/search/analytics")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to retrieve analytics"}
