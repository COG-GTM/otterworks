"""Tests for search API endpoints."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from app.config import AuthConfig
from app.main import create_app
from app.services.meilisearch_client import record_search_analytics

SERVICE_TOKEN = "test-service-token"


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

    @pytest.fixture()
    def token_client(self, app_config, mock_meilisearch_client):
        """Client for an app with a service token configured (auth on or off)."""

        def _make(require_auth: bool = True, service_token: str = SERVICE_TOKEN):
            config = replace(
                app_config,
                auth=AuthConfig(service_token=service_token, require_auth=require_auth),
            )
            with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
                mock_cls.return_value = mock_meilisearch_client
                flask_app = create_app(config)
            flask_app.config["TESTING"] = True
            return flask_app.test_client()

        return _make

    @pytest.fixture(autouse=True)
    def _seed_other_users_queries(self):
        record_search_analytics("acme acquisition codename", 0)
        yield

    def _auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_analytics_returns_data_with_service_token(self, token_client):
        """Service-token callers receive analytics data."""
        client = token_client()
        response = client.get(
            "/api/v1/search/analytics", headers=self._auth(SERVICE_TOKEN)
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "popular_queries" in data
        assert "zero_result_queries" in data
        assert "total_searches" in data
        assert "avg_results_per_query" in data

    @pytest.mark.parametrize("require_auth", [True, False])
    def test_analytics_rejects_end_user(self, token_client, require_auth):
        """A gateway-authenticated user cannot read other users' queries."""
        client = token_client(require_auth=require_auth)
        response = client.get(
            "/api/v1/search/analytics", headers={"X-User-ID": "user-attacker"}
        )
        assert response.status_code == 403
        assert b"acme acquisition codename" not in response.data

    @pytest.mark.parametrize("require_auth", [True, False])
    def test_analytics_rejects_wrong_token(self, token_client, require_auth):
        client = token_client(require_auth=require_auth)
        response = client.get(
            "/api/v1/search/analytics",
            headers={**self._auth("not-the-token"), "X-User-ID": "user-attacker"},
        )
        assert response.status_code == 403

    def test_analytics_rejects_anonymous_when_auth_disabled(self, client):
        """REQUIRE_AUTH=false does not open the analytics endpoint."""
        response = client.get("/api/v1/search/analytics")
        assert response.status_code == 403
        assert b"acme acquisition codename" not in response.data

    def test_analytics_fails_closed_without_configured_token(self, token_client):
        """With no service token configured, nobody can read analytics."""
        client = token_client(require_auth=False, service_token="")
        response = client.get("/api/v1/search/analytics", headers=self._auth(""))
        assert response.status_code == 403
        response = client.get(
            "/api/v1/search/analytics", headers={"Authorization": "Bearer"}
        )
        assert response.status_code == 403
