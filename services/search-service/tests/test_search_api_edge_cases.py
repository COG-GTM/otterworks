"""Tests for search API edge cases: suggest, analytics, chaos and error paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api import search as search_api


@pytest.fixture(autouse=True)
def reset_redis_singleton(monkeypatch):
    """Never let a Redis client leak between tests."""
    monkeypatch.setattr(search_api, "_redis_client", None)
    yield
    monkeypatch.setattr(search_api, "_redis_client", None)


class TestRedisHelpers:
    """Tests for the lazy Redis client and the chaos-flag lookup."""

    def test_redis_client_is_created_once_from_the_environment(self, monkeypatch):
        """The client is built from REDIS_HOST/PORT and then reused."""
        monkeypatch.setenv("REDIS_HOST", "redis.internal")
        monkeypatch.setenv("REDIS_PORT", "6380")

        with patch.object(search_api.redis_lib, "Redis") as redis_cls:
            first = search_api._get_redis()
            second = search_api._get_redis()

        redis_cls.assert_called_once_with(
            host="redis.internal", port=6380, decode_responses=True, socket_timeout=1
        )
        assert first is second

    def test_chaos_flag_is_reported_when_the_key_exists(self, monkeypatch):
        """A present Redis key activates the chaos path."""
        client = MagicMock()
        client.exists.return_value = 1
        monkeypatch.setattr(search_api, "_redis_client", client)

        assert search_api._chaos_active("chaos:flag") is True

    def test_chaos_flag_is_false_when_redis_is_unreachable(self, monkeypatch):
        """Redis being down must never break the request path."""
        client = MagicMock()
        client.exists.side_effect = RuntimeError("connection refused")
        monkeypatch.setattr(search_api, "_redis_client", client)

        assert search_api._chaos_active("chaos:flag") is False


class TestSearchEndpointErrors:
    """Tests for GET /api/v1/search/ failure handling."""

    @pytest.mark.parametrize("params", ["page=abc", "size=xyz"])
    def test_non_numeric_pagination_is_rejected(self, client, params):
        """A non-integer page or size returns 400."""
        response = client.get(f"/api/v1/search/?q=plan&{params}")
        assert response.status_code == 400
        assert response.get_json()["error"] == "Invalid page or size parameter"

    def test_pagination_bounds_are_clamped(self, client, mock_meilisearch_client):
        """page < 1 and size > 100 are clamped to the allowed range."""
        client.get("/api/v1/search/?q=plan&type=document&page=0&size=500")

        params = mock_meilisearch_client.index.return_value.search.call_args.args[1]
        assert params["limit"] == 100
        assert params["offset"] == 0

    def test_invalid_filter_from_meilisearch_returns_400(self, client, mock_meilisearch_client):
        """A ValueError raised by the service maps to a 400."""
        mock_meilisearch_client.index.return_value.search.side_effect = ValueError("bad filter")

        response = client.get("/api/v1/search/?q=plan")

        assert response.status_code == 400
        assert response.get_json()["error"] == "bad filter"

    def test_unexpected_backend_failure_returns_500(self, client, mock_meilisearch_client):
        """Any other backend error is reported as a 500 without leaking detail."""
        mock_meilisearch_client.index.return_value.search.side_effect = RuntimeError("boom")

        response = client.get("/api/v1/search/?q=plan")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Search failed"}


class TestSuggestEndpoint:
    """Tests for GET /api/v1/search/suggest."""

    @pytest.mark.parametrize("prefix", ["", "a"])
    def test_short_prefixes_return_no_suggestions(self, client, prefix):
        """Prefixes shorter than two characters short-circuit."""
        response = client.get(f"/api/v1/search/suggest?q={prefix}")
        assert response.status_code == 200
        assert response.get_json() == {"suggestions": [], "query": prefix}

    def test_suggestions_are_returned_for_a_valid_prefix(self, client, mock_meilisearch_client):
        """Matching titles are returned in index order."""
        mock_meilisearch_client.index.return_value.search.return_value = {
            "hits": [{"title": "Plan A"}],
            "estimatedTotalHits": 1,
        }

        response = client.get("/api/v1/search/suggest?q=pl")

        assert response.status_code == 200
        assert response.get_json() == {"suggestions": ["Plan A"], "query": "pl"}

    def test_backend_failure_degrades_to_an_empty_suggestion_list(
        self, client, mock_meilisearch_client
    ):
        """Autocomplete never fails the request; it returns no suggestions."""
        mock_meilisearch_client.index.return_value.search.side_effect = RuntimeError("down")

        response = client.get("/api/v1/search/suggest?q=pl")

        assert response.status_code == 200
        assert response.get_json() == {"suggestions": [], "query": "pl"}

    def test_chaos_flag_enables_the_ranking_score_path(self, client, mock_meilisearch_client):
        """With the chaos flag set, suggestions are ranked by _rankingScore."""
        mock_meilisearch_client.index.return_value.search.return_value = {
            "hits": [],
            "estimatedTotalHits": 0,
        }

        with patch.object(search_api, "_chaos_active", return_value=True), patch.object(
            search_api.MeiliSearchService, "suggest"
        ) as suggest:
            suggest.return_value = [
                {"title": "low", "_rankingScore": 0.1},
                {"title": "high", "_rankingScore": 0.9},
            ]
            response = client.get("/api/v1/search/suggest?q=pl")

        assert response.status_code == 200
        assert [s["title"] for s in response.get_json()["suggestions"]] == ["high", "low"]

    def test_chaos_path_crashes_on_an_empty_index(self, client, mock_meilisearch_client):
        """The chaos path's _rankingScore lookup fails when there are no hits.

        This is the injected chaos behaviour (a KeyError bubbling out as a 500),
        asserted here so the branch is covered and the behaviour is pinned.
        """
        mock_meilisearch_client.index.return_value.search.return_value = {
            "hits": [],
            "estimatedTotalHits": 0,
        }

        with patch.object(search_api, "_chaos_active", return_value=True):
            with pytest.raises(KeyError, match="_rankingScore"):
                client.get("/api/v1/search/suggest?q=pl")


class TestAdvancedSearchEndpoint:
    """Tests for POST /api/v1/search/advanced."""

    def test_empty_body_is_treated_as_an_empty_filter_set(self, client):
        """A POST with no filters performs a wildcard search rather than failing."""
        response = client.post("/api/v1/search/advanced", json={})
        assert response.status_code == 200
        assert response.get_json()["query"] == "*"

    def test_owner_scope_comes_from_the_gateway_header(self, client, mock_meilisearch_client):
        """The caller cannot spoof owner_id in the body; the header wins."""
        client.post(
            "/api/v1/search/advanced",
            json={"q": "plan", "type": "document", "owner_id": "someone-else"},
            headers={"X-User-ID": "user-1"},
        )

        params = mock_meilisearch_client.index.return_value.search.call_args.args[1]
        assert params["filter"] == 'type = "document" AND owner_id = "user-1"'

    @pytest.mark.parametrize("body", [{"page": "abc"}, {"size": None}])
    def test_invalid_pagination_is_rejected(self, client, body):
        """Non-numeric pagination values return 400."""
        response = client.post("/api/v1/search/advanced", json=body)
        assert response.status_code == 400
        assert response.get_json()["error"] == "Invalid page or size parameter"

    def test_backend_failure_returns_500(self, client, mock_meilisearch_client):
        """An unexpected backend error is reported as a 500."""
        mock_meilisearch_client.index.return_value.search.side_effect = RuntimeError("boom")

        response = client.post("/api/v1/search/advanced", json={"q": "plan"})

        assert response.status_code == 500
        assert response.get_json() == {"error": "Advanced search failed"}


class TestAnalyticsEndpoint:
    """Tests for GET /api/v1/search/analytics."""

    def test_analytics_are_returned(self, client):
        """The endpoint exposes the analytics aggregate."""
        response = client.get("/api/v1/search/analytics")

        assert response.status_code == 200
        body = response.get_json()
        assert "popular_queries" in body
        assert "total_searches" in body

    def test_analytics_failure_returns_500(self, client):
        """A failure while aggregating analytics is reported as a 500."""
        with patch(
            "app.api.search.get_search_analytics", side_effect=RuntimeError("boom")
        ):
            response = client.get("/api/v1/search/analytics")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to retrieve analytics"}
