"""Tests for search API endpoints."""

from __future__ import annotations

import io

import pytest

from app.api.search import MAX_SEARCH_BODY_BYTES, MAX_TAG_LENGTH, MAX_TAGS
from app.services import meilisearch_client
from app.services.meilisearch_client import MAX_ANALYTICS_ENTRIES, MAX_QUERY_LENGTH


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

    def test_search_rejects_oversized_query(self, client, mock_meilisearch_client):
        """Queries longer than MAX_QUERY_LENGTH are rejected before searching."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.reset_mock()
        response = client.get(f"/api/v1/search/?q={'a' * (MAX_QUERY_LENGTH + 1)}")
        assert response.status_code == 400
        mock_index.search.assert_not_called()

    def test_search_accepts_max_length_query(self, client):
        """A query exactly MAX_QUERY_LENGTH characters long is accepted."""
        response = client.get(f"/api/v1/search/?q={'a' * MAX_QUERY_LENGTH}")
        assert response.status_code == 200

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

    def test_advanced_search_rejects_oversized_query(self, client, mock_meilisearch_client):
        """Oversized 'q' is rejected and never reaches MeiliSearch or analytics."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.reset_mock()
        response = client.post(
            "/api/v1/search/advanced", json={"q": "A" * (MAX_QUERY_LENGTH + 1)}
        )
        assert response.status_code == 400
        mock_index.search.assert_not_called()

    def test_advanced_search_rejects_non_string_query(self, client):
        response = client.post("/api/v1/search/advanced", json={"q": ["a", "b"]})
        assert response.status_code == 400

    def test_advanced_search_rejects_non_object_body(self, client):
        response = client.post("/api/v1/search/advanced", json=["q"])
        assert response.status_code == 400

    def test_advanced_search_rejects_oversized_body(self, client):
        """Bodies larger than MAX_SEARCH_BODY_BYTES are rejected with 413."""
        response = client.post(
            "/api/v1/search/advanced",
            data="{" + " " * MAX_SEARCH_BODY_BYTES + "}",
            content_type="application/json",
        )
        assert response.status_code == 413

    def test_advanced_search_rejects_oversized_chunked_body(self, client, mock_meilisearch_client):
        """Streamed bodies without Content-Length are capped as well."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.reset_mock()
        body = b'{"q": "' + b"A" * (MAX_SEARCH_BODY_BYTES * 2) + b'"}'
        response = client.post(
            "/api/v1/search/advanced",
            input_stream=io.BytesIO(body),
            content_type="application/json",
            environ_overrides={"wsgi.input_terminated": True},
        )
        assert response.status_code == 413
        mock_index.search.assert_not_called()

    @pytest.mark.parametrize("body", [[], False, 0, ""])
    def test_advanced_search_rejects_falsy_non_object_body(self, client, mock_meilisearch_client, body):
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.reset_mock()
        response = client.post("/api/v1/search/advanced", json=body)
        assert response.status_code == 400
        mock_index.search.assert_not_called()

    def test_index_endpoint_not_subject_to_search_body_cap(self, client):
        """The search body cap must not apply to indexing payloads."""
        response = client.post(
            "/api/v1/search/index/document",
            json={"id": "doc-big", "title": "Big", "content": "x" * (MAX_SEARCH_BODY_BYTES * 2)},
        )
        assert response.status_code != 413

    def test_advanced_search_rejects_too_many_tags(self, client):
        response = client.post(
            "/api/v1/search/advanced", json={"tags": [f"t{i}" for i in range(MAX_TAGS + 1)]}
        )
        assert response.status_code == 400

    def test_advanced_search_rejects_oversized_tag(self, client):
        response = client.post(
            "/api/v1/search/advanced", json={"tags": ["x" * (MAX_TAG_LENGTH + 1)]}
        )
        assert response.status_code == 400

    def test_advanced_search_rejects_non_string_tags(self, client):
        response = client.post("/api/v1/search/advanced", json={"tags": "finance"})
        assert response.status_code == 400


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


class TestSearchAnalyticsBounds:
    """In-memory analytics must stay bounded in entry count and entry size."""

    def test_recorded_query_is_truncated(self):
        meilisearch_client.record_search_analytics("Z" * (MAX_QUERY_LENGTH * 4), 0)
        stored = meilisearch_client._search_analytics["queries"][-1]["query"]
        assert len(stored) == MAX_QUERY_LENGTH

    def test_entry_count_is_capped(self):
        for i in range(MAX_ANALYTICS_ENTRIES + 5):
            meilisearch_client.record_search_analytics(f"q{i}", 1)
        queries = meilisearch_client._search_analytics["queries"]
        assert len(queries) == MAX_ANALYTICS_ENTRIES
        assert queries[-1]["query"] == f"q{MAX_ANALYTICS_ENTRIES + 4}"
