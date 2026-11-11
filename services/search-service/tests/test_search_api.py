"""Tests for search API endpoints."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from meilisearch.errors import MeilisearchApiError


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

    def test_search_meilisearch_error_not_disclosed(self, client, mock_meilisearch_client):
        """A MeiliSearch API error yields a generic 400 without backend details."""
        meili_response = MagicMock()
        meili_response.status_code = 400
        meili_response.text = json.dumps(
            {
                "message": "Attribute `secret_attr` is not filterable on index `otterworks-internal`.",
                "code": "invalid_search_filter",
                "type": "invalid_request",
                "link": "https://docs.meilisearch.com/errors#invalid_search_filter",
            }
        )
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.side_effect = MeilisearchApiError("boom", meili_response)

        response = client.get("/api/v1/search/?q=test")

        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid search request"}
        body = response.get_data(as_text=True)
        for leaked in ("secret_attr", "otterworks-internal", "invalid_search_filter", "meilisearch"):
            assert leaked not in body

    def test_search_page_beyond_max_total_hits(self, client, mock_meilisearch_client):
        """Pages past MeiliSearch's maxTotalHits are rejected before querying."""
        response = client.get("/api/v1/search/?q=test&page=1000000000000000000000000000")
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid page or size parameter"}
        mock_meilisearch_client.index.return_value.search.assert_not_called()

    def test_search_last_allowed_page(self, client, mock_meilisearch_client):
        """A final partial page that starts within maxTotalHits is still served."""
        response = client.get("/api/v1/search/?q=test&page=11&size=99")
        assert response.status_code == 200

    def test_search_page_starting_at_max_total_hits(self, client, mock_meilisearch_client):
        """A page whose offset reaches maxTotalHits is rejected."""
        response = client.get("/api/v1/search/?q=test&page=51&size=20")
        assert response.status_code == 400
        mock_meilisearch_client.index.return_value.search.assert_not_called()


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
