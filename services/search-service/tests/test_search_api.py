"""Tests for search API endpoints."""

from __future__ import annotations

from meilisearch.errors import MeilisearchCommunicationError


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

    def test_suggest_orders_by_ranking_score(self, client, mock_meilisearch_client):
        """Suggestions are merged across indexes and sorted by _rankingScore."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.side_effect = [
            {"hits": [{"title": "Team notes", "_rankingScore": 0.4}, {"title": "Test plan", "_rankingScore": 0.9}]},
            {"hits": [{"name": "test.csv", "_rankingScore": 0.7}, {"name": "Team notes", "_rankingScore": 0.95}]},
        ]

        response = client.get("/api/v1/search/suggest?q=te")
        assert response.status_code == 200
        assert response.get_json()["suggestions"] == ["Team notes", "Test plan", "test.csv"]
        assert mock_index.search.call_args[0][1]["showRankingScore"] is True

    def test_suggest_hits_without_ranking_score(self, client, mock_meilisearch_client):
        """Hits missing _rankingScore must not crash the endpoint (regression)."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {"hits": [{"title": "Test Doc 1"}, {"title": "Test Doc 2"}]}

        response = client.get("/api/v1/search/suggest?q=te")
        assert response.status_code == 200
        assert response.get_json()["suggestions"] == ["Test Doc 1", "Test Doc 2"]

    def test_suggest_backend_failure_returns_empty(self, client, mock_meilisearch_client):
        """A MeiliSearch error degrades to an empty list instead of a 5xx."""
        mock_meilisearch_client.index.return_value.search.side_effect = RuntimeError("meili down")

        response = client.get("/api/v1/search/suggest?q=te")
        assert response.status_code == 200
        assert response.get_json()["suggestions"] == []

    def test_suggest_one_index_failure_keeps_other_results(self, client, mock_meilisearch_client):
        """A files-index failure must not discard document suggestions."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.side_effect = [
            {"hits": [{"title": "Test Doc", "_rankingScore": 0.8}]},
            MeilisearchCommunicationError("files index unreachable"),
        ]

        response = client.get("/api/v1/search/suggest?q=te")
        assert response.status_code == 200
        assert response.get_json()["suggestions"] == ["Test Doc"]

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
