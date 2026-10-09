"""Tests for search API endpoints."""

from __future__ import annotations

import json

import meilisearch
import requests

from app.services.meilisearch_client import MAX_TOTAL_HITS


def _meili_api_error(code: str, message: str) -> meilisearch.errors.MeilisearchApiError:
    """Build a MeilisearchApiError the way the SDK does from an HTTP 400."""
    response = requests.Response()
    response.status_code = 400
    response._content = json.dumps(
        {
            "message": message,
            "code": code,
            "type": "invalid_request",
            "link": f"https://docs.meilisearch.com/errors#{code}",
        }
    ).encode()
    return meilisearch.errors.MeilisearchApiError(message, response)


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

    def test_search_meilisearch_error_is_generic(self, client, mock_meilisearch_client):
        """MeiliSearch error details are logged server-side, never returned."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.side_effect = _meili_api_error(
            "invalid_search_filter",
            "Attribute `secret_attr` is not filterable. Available filterable attributes are: `owner_id`.",
        )

        response = client.get("/api/v1/search/?q=test")
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid search request"}
        body = response.get_data(as_text=True)
        for leaked in ("invalid_search_filter", "filterable", "owner_id", "meilisearch.com", "invalid_request"):
            assert leaked not in body

    def test_search_page_beyond_result_window_rejected(self, client, mock_meilisearch_client):
        """A page past maxTotalHits is rejected before MeiliSearch is queried."""
        mock_index = mock_meilisearch_client.index.return_value
        response = client.get("/api/v1/search/?q=x&page=1000000000000000000000000000")
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid page or size parameter"}
        mock_index.search.assert_not_called()

        response = client.get(f"/api/v1/search/?q=x&page={MAX_TOTAL_HITS // 100 + 1}&size=100")
        assert response.status_code == 400
        mock_index.search.assert_not_called()

    def test_search_last_page_in_result_window_allowed(self, client, mock_meilisearch_client):
        """Pages starting inside maxTotalHits are still served, including partial last pages."""
        page = MAX_TOTAL_HITS // 100
        response = client.get(f"/api/v1/search/?q=x&page={page}&size=100")
        assert response.status_code == 200
        assert response.get_json()["page"] == page

        response = client.get("/api/v1/search/?q=x&page=11&size=91")
        assert response.status_code == 200
        assert response.get_json()["page"] == 11


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

    def test_advanced_search_page_beyond_result_window_rejected(self, client, mock_meilisearch_client):
        """Advanced search rejects pages past maxTotalHits without querying."""
        mock_index = mock_meilisearch_client.index.return_value
        response = client.post("/api/v1/search/advanced", json={"q": "x", "page": 10**27})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid page or size parameter"}
        mock_index.search.assert_not_called()


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
