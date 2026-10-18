"""Tests for search API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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


class TestSuggestRanking:
    """Regression tests for the ranking-score enrichment in /suggest."""

    def test_suggest_does_not_500_when_ranking_flag_set(self, client, mock_meilisearch_client):
        """Suggest must not crash with KeyError when the ranking path flag is set in Redis."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {"hits": [{"title": "Quarterly Report"}]}

        with patch("redis.Redis.exists", return_value=1):
            response = client.get("/api/v1/search/suggest?q=qu")

        assert response.status_code == 200
        assert response.get_json()["suggestions"] == ["Quarterly Report"]

    def test_suggest_empty_index_does_not_500_when_ranking_flag_set(self, client):
        """Suggest on an empty index returns an empty list rather than a 500."""
        with patch("redis.Redis.exists", return_value=1):
            response = client.get("/api/v1/search/suggest?q=zz")

        assert response.status_code == 200
        assert response.get_json()["suggestions"] == []

    def test_suggest_sorted_by_ranking_score_across_indexes(self, client, mock_meilisearch_client):
        """Suggestions from both indexes are merged and ordered by _rankingScore."""
        docs_index = MagicMock()
        docs_index.search.return_value = {
            "hits": [
                {"title": "Team Roadmap", "_rankingScore": 0.4},
                {"title": "Team Notes", "_rankingScore": 0.9},
            ]
        }
        files_index = MagicMock()
        files_index.search.return_value = {
            "hits": [
                {"name": "team.png", "_rankingScore": 0.7},
                {"name": "Team Notes", "_rankingScore": 0.95},
                {"name": "no-score.txt"},
            ]
        }
        mock_meilisearch_client.index.side_effect = lambda name: (
            docs_index if name == "test-otterworks-documents" else files_index
        )

        response = client.get("/api/v1/search/suggest?q=te")

        assert response.status_code == 200
        assert response.get_json()["suggestions"] == ["Team Notes", "team.png", "Team Roadmap", "no-score.txt"]
        opts = docs_index.search.call_args[0][1]
        assert opts["showRankingScore"] is True

    def test_suggest_keeps_healthy_index_when_other_index_fails(self, client, mock_meilisearch_client):
        """A failing files index must not drop suggestions from the documents index."""
        from meilisearch.errors import MeilisearchCommunicationError

        docs_index = MagicMock()
        docs_index.search.return_value = {"hits": [{"title": "Design Doc", "_rankingScore": 0.8}]}
        files_index = MagicMock()
        files_index.search.side_effect = MeilisearchCommunicationError("connection refused")
        mock_meilisearch_client.index.side_effect = lambda name: (
            docs_index if name == "test-otterworks-documents" else files_index
        )

        response = client.get("/api/v1/search/suggest?q=de")

        assert response.status_code == 200
        assert response.get_json()["suggestions"] == ["Design Doc"]

    def test_suggest_fetches_more_pages_when_duplicates_leave_it_short(self, app, mock_meilisearch_client):
        """Duplicate titles on the first page trigger fetching further pages."""
        pages = {
            0: [{"title": "Report", "_rankingScore": 0.9}] * 3,
            3: [{"title": "Report Q1", "_rankingScore": 0.8}, {"title": "Report Q2", "_rankingScore": 0.7}],
        }
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.side_effect = lambda q, opts: {"hits": pages.get(opts["offset"], [])}

        suggestions = app.config["SEARCH_SERVICE"].suggest("re", size=3)

        assert suggestions == ["Report", "Report Q1", "Report Q2"]
