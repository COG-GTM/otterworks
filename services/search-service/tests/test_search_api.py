"""Tests for search API endpoints."""

from __future__ import annotations

import dataclasses

import pytest

import app.services.meilisearch_client as meili_module


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

        response = client.get("/api/v1/search/suggest?q=te", headers={"X-User-ID": "user-1"})
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["suggestions"]) >= 1

    def test_suggest_filters_by_caller(self, client, mock_meilisearch_client):
        """Suggest only queries the caller's own documents and files."""
        mock_index = mock_meilisearch_client.index.return_value

        response = client.get("/api/v1/search/suggest?q=la", headers={"X-User-ID": "user-b"})
        assert response.status_code == 200
        assert mock_index.search.call_count == 2
        for call in mock_index.search.call_args_list:
            assert call.args[1]["filter"] == 'owner_id = "user-b"'

    def test_suggest_without_identity_returns_nothing(self, client, mock_meilisearch_client):
        """Suggest without a caller identity never queries the indexes."""
        mock_index = mock_meilisearch_client.index.return_value

        response = client.get("/api/v1/search/suggest?q=la")
        assert response.status_code == 200
        assert response.get_json()["suggestions"] == []
        mock_index.search.assert_not_called()

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

    @pytest.fixture(autouse=True)
    def _reset_analytics(self):
        with meili_module._analytics_lock:
            meili_module._search_analytics["queries"] = []
            meili_module._search_analytics["total_searches"] = 0
            meili_module._search_analytics["total_results"] = 0
        yield

    def test_analytics_returns_data(self, client):
        """Analytics endpoint returns analytics data."""
        response = client.get("/api/v1/search/analytics", headers={"X-User-ID": "user-1"})
        assert response.status_code == 200
        data = response.get_json()
        assert "popular_queries" in data
        assert "zero_result_queries" in data
        assert "total_searches" in data
        assert "avg_results_per_query" in data

    def test_analytics_scoped_to_caller(self, client):
        """A user only sees their own search terms."""
        client.get("/api/v1/search/?q=layoff", headers={"X-User-ID": "alice"})
        client.get("/api/v1/search/?q=roadmap", headers={"X-User-ID": "mallory"})

        data = client.get("/api/v1/search/analytics", headers={"X-User-ID": "mallory"}).get_json()
        assert data["total_searches"] == 1
        assert [q["query"] for q in data["popular_queries"]] == ["roadmap"]

    def test_analytics_without_identity_forbidden(self, client):
        """Analytics without a caller identity or service token is rejected."""
        response = client.get("/api/v1/search/analytics")
        assert response.status_code == 403

    def test_analytics_global_for_service_token(self, client, app):
        """Trusted internal callers with the service token get the global aggregate."""
        cfg = app.config["APP_CONFIG"]
        app.config["APP_CONFIG"] = dataclasses.replace(
            cfg, auth=dataclasses.replace(cfg.auth, service_token="internal-token")
        )
        client.get("/api/v1/search/?q=layoff", headers={"X-User-ID": "alice"})
        client.get("/api/v1/search/?q=roadmap", headers={"X-User-ID": "mallory"})

        data = client.get(
            "/api/v1/search/analytics", headers={"Authorization": "Bearer internal-token"}
        ).get_json()
        assert data["total_searches"] == 2

        response = client.get(
            "/api/v1/search/analytics", headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 403
