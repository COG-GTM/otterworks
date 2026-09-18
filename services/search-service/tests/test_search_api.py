"""Tests for search API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import meilisearch.errors


class TestSearchEndpoint:
    """Tests for GET /api/v1/search/."""

    def test_search_requires_query(self, client):
        """Search without 'q' returns 400."""
        response = client.get("/api/v1/search/")
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_search_with_query(self, client, mock_meilisearch_client):
        """Search with a valid query returns results."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [
                {
                    "id": "doc-1",
                    "title": "Test Document",
                    "content": "Some content here",
                    "type": "document",
                    "owner_id": "user-1",
                    "tags": ["test"],
                    "_formatted": {
                        "title": "Test Document",
                        "content": "Some <em>content</em> here",
                    },
                }
            ],
        }

        response = client.get("/api/v1/search/?q=test")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] >= 1
        assert len(data["results"]) >= 1
        assert data["query"] == "test"

    def test_search_with_type_filter(self, client, mock_meilisearch_client):
        """Search with type filter."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.get("/api/v1/search/?q=test&type=file")
        assert response.status_code == 200

    def test_search_pagination(self, client, mock_meilisearch_client):
        """Search with pagination params."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.get("/api/v1/search/?q=test&page=2&size=10")
        assert response.status_code == 200
        data = response.get_json()
        assert data["page"] == 2
        assert data["page_size"] == 10

    def test_search_invalid_page(self, client):
        """Search with non-numeric page returns 400."""
        response = client.get("/api/v1/search/?q=test&page=not-a-number")
        assert response.status_code == 400


class TestSuggestEndpoint:
    """Tests for GET /api/v1/search/suggest."""

    def test_suggest_short_query(self, client):
        """Suggest with query shorter than 2 chars returns empty."""
        response = client.get("/api/v1/search/suggest?q=a")
        assert response.status_code == 200
        data = response.get_json()
        assert data["suggestions"] == []

    def test_suggest_with_prefix(self, client, mock_meilisearch_client):
        """Suggest with valid prefix returns suggestions."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 2,
            "hits": [
                {"title": "Test Doc 1"},
                {"title": "Test Doc 2"},
            ],
        }

        response = client.get("/api/v1/search/suggest?q=te")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["suggestions"]) >= 1

    def test_suggest_empty_query(self, client):
        """Suggest with empty query returns empty list."""
        response = client.get("/api/v1/search/suggest?q=")
        assert response.status_code == 200
        data = response.get_json()
        assert data["suggestions"] == []


class TestAdvancedSearchEndpoint:
    """Tests for POST /api/v1/search/advanced."""

    def test_advanced_search_with_filters(self, client, mock_meilisearch_client):
        """Advanced search with multiple filters."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.post(
            "/api/v1/search/advanced",
            json={
                "q": "report",
                "type": "document",
                "owner_id": "user-1",
                "tags": ["finance"],
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
                "page": 1,
                "size": 10,
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "results" in data
        assert "total" in data

    def test_advanced_search_empty_body(self, client, mock_meilisearch_client):
        """Advanced search with empty body still works (match_all)."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.post("/api/v1/search/advanced", json={})
        assert response.status_code == 200


class TestAnalyticsEndpoint:
    """Tests for GET /api/v1/search/analytics."""

    def test_analytics_returns_data(self, client):
        """Analytics endpoint returns analytics data."""
        response = client.get("/api/v1/search/analytics")
        assert response.status_code == 200
        data = response.get_json()
        assert "popular_queries" in data
        assert "zero_result_queries" in data
        assert "total_searches" in data
        assert "avg_results_per_query" in data


class TestTenantScoping:
    """Every read is restricted to the caller's own owner id."""

    def test_search_requires_caller_identity(self, authed_client):
        """A search without gateway-injected identity is refused, not answered."""
        response = authed_client.get("/api/v1/search/?q=test")
        assert response.status_code == 401

    def test_search_filters_on_caller_owner_id(self, authed_client, mock_meilisearch_client):
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {"estimatedTotalHits": 0, "hits": []}

        response = authed_client.get(
            "/api/v1/search/?q=test", headers={"X-User-ID": "user-1"}
        )
        assert response.status_code == 200
        params = mock_index.search.call_args[0][1]
        assert 'owner_id = "user-1"' in params["filter"]

    def test_suggest_filters_on_caller_owner_id(self, authed_client, mock_meilisearch_client):
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {"estimatedTotalHits": 0, "hits": []}

        response = authed_client.get(
            "/api/v1/search/suggest?q=te", headers={"X-User-ID": "user-1"}
        )
        assert response.status_code == 200
        params = mock_index.search.call_args[0][1]
        assert params["filter"] == 'owner_id = "user-1"'

    def test_advanced_search_filters_on_caller_owner_id(
        self, authed_client, mock_meilisearch_client
    ):
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {"estimatedTotalHits": 0, "hits": []}

        response = authed_client.post(
            "/api/v1/search/advanced",
            json={"q": "report", "owner_id": "someone-else"},
            headers={"X-User-ID": "user-1"},
        )
        assert response.status_code == 200
        params = mock_index.search.call_args[0][1]
        assert 'owner_id = "user-1"' in params["filter"]
        assert "someone-else" not in params["filter"]

    def test_analytics_requires_caller_identity(self, authed_client):
        response = authed_client.get("/api/v1/search/analytics")
        assert response.status_code == 401

    def test_analytics_only_counts_the_callers_queries(
        self, authed_client, mock_meilisearch_client
    ):
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {"estimatedTotalHits": 0, "hits": []}

        authed_client.get(
            "/api/v1/search/?q=other-tenant-secret", headers={"X-User-ID": "user-2"}
        )
        response = authed_client.get(
            "/api/v1/search/analytics", headers={"X-User-ID": "user-1"}
        )
        assert response.status_code == 200
        queries = [entry["query"] for entry in response.get_json()["popular_queries"]]
        assert "other-tenant-secret" not in queries


class TestInputHandling:
    """Malformed filter input is rejected without echoing engine errors."""

    def test_invalid_type_rejected(self, client):
        response = client.get("/api/v1/search/?q=test&type=' OR 1=1 --")
        assert response.status_code == 400

    def test_invalid_date_filter_rejected(self, client):
        response = client.post(
            "/api/v1/search/advanced", json={"q": "x", "date_from": "' OR '1'='1"}
        )
        assert response.status_code == 400

    def test_engine_error_is_not_returned_to_the_caller(self, client, mock_meilisearch_client):
        mock_index = mock_meilisearch_client.index.return_value
        fake_response = MagicMock()
        fake_response.status_code = 400
        fake_response.text = ""
        mock_index.search.side_effect = meilisearch.errors.MeilisearchApiError(
            'Invalid syntax for the filter parameter: owner_id = "x"', fake_response
        )

        response = client.get("/api/v1/search/?q=test")
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid search request"}
