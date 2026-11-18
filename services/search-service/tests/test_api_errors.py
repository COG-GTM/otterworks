"""Tests for API validation and error paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api import search as search_api
from tests.helpers import meili_api_error


@pytest.fixture()
def lenient_client(app):
    app.config["PROPAGATE_EXCEPTIONS"] = False
    return app.test_client()


@pytest.fixture()
def no_chaos():
    with patch.object(search_api, "_chaos_active", return_value=False):
        yield


class TestIndexApiErrors:
    @pytest.mark.parametrize("path", ["/api/v1/search/index/document", "/api/v1/search/index/file"])
    def test_empty_body_400(self, client, path):
        response = client.post(path, json={})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Request body is required"}

    def test_file_missing_id_400(self, client):
        response = client.post("/api/v1/search/index/file", json={"name": "a"})
        assert response.status_code == 400
        assert "id" in response.get_json()["error"]

    @pytest.mark.parametrize(
        ("path", "body", "message"),
        [
            ("/api/v1/search/index/document", {"id": "d", "title": "t"}, "Failed to index document"),
            ("/api/v1/search/index/file", {"id": "f", "name": "n"}, "Failed to index file"),
        ],
    )
    def test_backend_failure_500(self, client, mock_meilisearch_client, path, body, message):
        mock_meilisearch_client.index.return_value.add_documents.side_effect = ConnectionError("down")
        response = client.post(path, json=body)
        assert response.status_code == 500
        assert response.get_json() == {"error": message}

    def test_delete_not_found_404(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.get_document.side_effect = meili_api_error(404, "document_not_found")
        response = client.delete("/api/v1/search/index/file/missing")
        assert response.status_code == 404
        assert response.get_json() == {"status": "not_found", "id": "missing", "type": "file"}

    def test_delete_backend_failure_500(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.get_document.side_effect = ConnectionError("down")
        response = client.delete("/api/v1/search/index/document/d1")
        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to remove from index"}

    def test_reindex_returns_counts(self, client):
        with patch("app.services.indexer.Indexer._fetch_all_documents", return_value=[{"id": "d"}]), \
                patch("app.services.indexer.Indexer._fetch_all_files", return_value=[]):
            response = client.post("/api/v1/search/reindex")
        assert response.status_code == 200
        assert response.get_json()["indexed_counts"] == {"documents": 1, "files": 0}

    def test_reindex_failure_500(self, client):
        with patch("app.services.indexer.Indexer.reindex", side_effect=RuntimeError("boom")):
            response = client.post("/api/v1/search/reindex")
        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to reindex"}


class TestSearchApiErrors:
    def test_invalid_filter_400(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.search.side_effect = meili_api_error(400, "invalid_search_filter")
        response = client.get("/api/v1/search/?q=x")
        assert response.status_code == 400
        assert "Invalid search filter" in response.get_json()["error"]

    def test_search_failure_500(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.search.side_effect = ConnectionError("down")
        response = client.get("/api/v1/search/?q=x")
        assert response.status_code == 500
        assert response.get_json() == {"error": "Search failed"}

    def test_search_scoped_to_gateway_user(self, client, mock_meilisearch_client):
        client.get("/api/v1/search/?q=x&type=document", headers={"X-User-ID": "u-7"})
        params = mock_meilisearch_client.index.return_value.search.call_args.args[1]
        assert params["filter"] == 'type = "document" AND owner_id = "u-7"'

    def test_search_clamps_page_and_size(self, client):
        data = client.get("/api/v1/search/?q=x&page=0&size=1000").get_json()
        assert (data["page"], data["page_size"]) == (1, 100)

    def test_advanced_invalid_page_400(self, client):
        response = client.post("/api/v1/search/advanced", json={"page": "abc"})
        assert response.status_code == 400

    def test_advanced_owner_from_header_not_body(self, client, mock_meilisearch_client):
        client.post("/api/v1/search/advanced", json={"owner_id": "victim"}, headers={"X-User-ID": "me"})
        params = mock_meilisearch_client.index.return_value.search.call_args.args[1]
        assert params["filter"] == 'owner_id = "me"'

    def test_advanced_failure_500(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.search.side_effect = ConnectionError("down")
        response = client.post("/api/v1/search/advanced", json={"q": "x"})
        assert response.status_code == 500
        assert response.get_json() == {"error": "Advanced search failed"}

    def test_analytics_failure_500(self, client):
        with patch.object(search_api, "get_search_analytics", side_effect=RuntimeError("boom")):
            response = client.get("/api/v1/search/analytics")
        assert response.status_code == 500


class TestSuggestPaths:
    def test_suggest_failure_returns_empty(self, client, mock_meilisearch_client, no_chaos):
        mock_meilisearch_client.index.return_value.search.side_effect = ConnectionError("down")
        response = client.get("/api/v1/search/suggest?q=abc")
        assert response.status_code == 200
        assert response.get_json() == {"suggestions": [], "query": "abc"}

    def test_chaos_flag_checked(self, client):
        redis = MagicMock()
        redis.exists.return_value = 0
        with patch.object(search_api, "_get_redis", return_value=redis):
            assert client.get("/api/v1/search/suggest?q=abc").status_code == 200
        redis.exists.assert_called_once_with("chaos:search-service:suggest_500")

    def test_chaos_redis_error_treated_as_inactive(self):
        redis = MagicMock()
        redis.exists.side_effect = ConnectionError("down")
        with patch.object(search_api, "_get_redis", return_value=redis):
            assert search_api._chaos_active("k") is False

    @pytest.mark.parametrize("hits", [[], [{"title": "Alpha"}]])
    def test_chaos_flag_active_returns_500(self, lenient_client, mock_meilisearch_client, hits):
        mock_meilisearch_client.index.return_value.search.return_value = {"hits": hits}
        with patch.object(search_api, "_chaos_active", return_value=True):
            response = lenient_client.get("/api/v1/search/suggest?q=al")
        assert response.status_code == 500


class TestRedisClient:
    def test_lazy_singleton_from_env(self, monkeypatch):
        monkeypatch.setattr(search_api, "_redis_client", None)
        monkeypatch.setenv("REDIS_HOST", "redis.internal")
        monkeypatch.setenv("REDIS_PORT", "6380")
        with patch.object(search_api.redis_lib, "Redis") as redis_cls:
            first = search_api._get_redis()
            second = search_api._get_redis()
        assert first is second
        redis_cls.assert_called_once_with(
            host="redis.internal", port=6380, decode_responses=True, socket_timeout=1
        )
