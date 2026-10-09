"""Tests for search API endpoints."""

from __future__ import annotations


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


class TestSearchInputLimits:
    """Oversized search input is rejected and never retained in analytics."""

    def test_search_rejects_overlong_query(self, client, mock_meilisearch_client):
        mock_index = mock_meilisearch_client.index.return_value
        response = client.get("/api/v1/search/", query_string={"q": "a" * 513})
        assert response.status_code == 400
        mock_index.search.assert_not_called()

    def test_search_accepts_max_length_query(self, client, mock_meilisearch_client):
        response = client.get("/api/v1/search/", query_string={"q": "a" * 512})
        assert response.status_code == 200

    def test_advanced_rejects_overlong_query(self, client, mock_meilisearch_client):
        mock_index = mock_meilisearch_client.index.return_value
        response = client.post("/api/v1/search/advanced", json={"q": "a" * 513})
        assert response.status_code == 400
        mock_index.search.assert_not_called()

    def test_advanced_rejects_non_string_query(self, client):
        response = client.post("/api/v1/search/advanced", json={"q": ["a", "b"]})
        assert response.status_code == 400

    def test_advanced_rejects_non_object_body(self, client):
        response = client.post("/api/v1/search/advanced", json=["q"])
        assert response.status_code == 400

    def test_advanced_rejects_too_many_tags(self, client):
        response = client.post("/api/v1/search/advanced", json={"tags": [f"t{i}" for i in range(21)]})
        assert response.status_code == 400

    def test_advanced_rejects_invalid_tags(self, client):
        assert client.post("/api/v1/search/advanced", json={"tags": "finance"}).status_code == 400
        assert client.post("/api/v1/search/advanced", json={"tags": [1]}).status_code == 400
        assert client.post("/api/v1/search/advanced", json={"tags": ["x" * 129]}).status_code == 400

    def test_advanced_rejects_oversized_body(self, client, mock_meilisearch_client):
        mock_index = mock_meilisearch_client.index.return_value
        response = client.post("/api/v1/search/advanced", json={"q": "a", "pad": "x" * (64 * 1024)})
        assert response.status_code == 413
        mock_index.search.assert_not_called()

    def test_app_sets_max_content_length(self, app):
        assert app.config["MAX_CONTENT_LENGTH"] == 1024 * 1024

    def test_index_endpoint_not_bound_by_search_body_limit(self, client):
        response = client.post(
            "/api/v1/search/index/document",
            json={"id": "doc-big", "title": "Big", "content": "x" * (100 * 1024), "owner_id": "user-1"},
        )
        assert response.status_code == 201

    def test_analytics_stores_truncated_query(self):
        from app.services.meilisearch_client import (
            MAX_ANALYTICS_QUERY_LENGTH,
            _search_analytics,
            record_search_analytics,
        )

        record_search_analytics("q" * 10_000, 0)
        stored = _search_analytics["queries"][-1]["query"]
        assert stored == "q" * MAX_ANALYTICS_QUERY_LENGTH
