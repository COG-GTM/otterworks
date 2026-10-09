"""Tests for search API endpoints."""

from __future__ import annotations

import pytest

USER_HEADERS = {"X-User-ID": "user-1"}


class TestSearchEndpoint:
    """Tests for GET /api/v1/search/."""

    def test_search_requires_query(self, client):
        """Search without 'q' returns 400."""
        response = client.get("/api/v1/search/", headers=USER_HEADERS)
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

        response = client.get("/api/v1/search/?q=test", headers=USER_HEADERS)
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

        response = client.get("/api/v1/search/?q=test&type=file", headers=USER_HEADERS)
        assert response.status_code == 200

    def test_search_pagination(self, client, mock_meilisearch_client):
        """Search with pagination params."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.get(
            "/api/v1/search/?q=test&page=2&size=10", headers=USER_HEADERS
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["page"] == 2
        assert data["page_size"] == 10

    def test_search_invalid_page(self, client):
        """Search with non-numeric page returns 400."""
        response = client.get(
            "/api/v1/search/?q=test&page=not-a-number", headers=USER_HEADERS
        )
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
            headers=USER_HEADERS,
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

        response = client.post("/api/v1/search/advanced", json={}, headers=USER_HEADERS)
        assert response.status_code == 200


class TestOwnerScoping:
    """Search reads are always scoped to the caller's X-User-ID."""

    @pytest.mark.parametrize("headers", [{}, {"X-User-ID": ""}, {"X-User-ID": "   "}])
    def test_search_without_identity_is_rejected(
        self, client, mock_meilisearch_client, headers
    ):
        """A request with no caller identity gets 401 instead of an unscoped search."""
        response = client.get("/api/v1/search/?q=test", headers=headers)
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}
        mock_meilisearch_client.index.return_value.search.assert_not_called()

    @pytest.mark.parametrize("headers", [{}, {"X-User-ID": ""}, {"X-User-ID": "   "}])
    def test_advanced_search_without_identity_is_rejected(
        self, client, mock_meilisearch_client, headers
    ):
        """An empty-body advanced search with no identity must not list the whole index."""
        response = client.post("/api/v1/search/advanced", json={}, headers=headers)
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}
        mock_meilisearch_client.index.return_value.search.assert_not_called()

    def test_search_filters_by_caller(self, client, mock_meilisearch_client):
        """The owner filter comes from X-User-ID."""
        mock_index = mock_meilisearch_client.index.return_value
        response = client.get(
            "/api/v1/search/?q=test", headers={"X-User-ID": "user-42"}
        )
        assert response.status_code == 200
        for call in mock_index.search.call_args_list:
            assert 'owner_id = "user-42"' in call.args[1]["filter"]

    def test_advanced_search_ignores_body_owner(self, client, mock_meilisearch_client):
        """A body-supplied owner_id cannot widen or redirect the scope."""
        mock_index = mock_meilisearch_client.index.return_value
        response = client.post(
            "/api/v1/search/advanced",
            json={"owner_id": "victim"},
            headers={"X-User-ID": "user-42"},
        )
        assert response.status_code == 200
        assert mock_index.search.call_args_list
        for call in mock_index.search.call_args_list:
            assert 'owner_id = "user-42"' in call.args[1]["filter"]
            assert "victim" not in call.args[1]["filter"]

    def test_identity_required_even_when_require_auth_enabled(
        self, app_config, mock_meilisearch_client
    ):
        """With REQUIRE_AUTH on, a service-token-only caller still cannot search unscoped."""
        from dataclasses import replace
        from unittest.mock import patch

        from app.config import AuthConfig
        from app.main import create_app

        config = replace(
            app_config, auth=AuthConfig(service_token="svc-token", require_auth=True)
        )
        with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
            mock_cls.return_value = mock_meilisearch_client
            client = create_app(config).test_client()
        response = client.post(
            "/api/v1/search/advanced",
            json={},
            headers={"Authorization": "Bearer svc-token"},
        )
        assert response.status_code == 401
        mock_meilisearch_client.index.return_value.search.assert_not_called()


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
