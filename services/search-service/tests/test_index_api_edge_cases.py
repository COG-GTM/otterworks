"""Tests for indexing API error paths and 404 handling."""

from __future__ import annotations

from unittest.mock import patch

from app.services.indexer import Indexer


class TestIndexDocumentErrors:
    """Tests for POST /api/v1/search/index/document."""

    def test_backend_failure_returns_500(self, client):
        """An unexpected indexing failure is reported as a 500."""
        with patch.object(Indexer, "index_document", side_effect=RuntimeError("boom")):
            response = client.post(
                "/api/v1/search/index/document", json={"id": "d-1", "title": "T"}
            )

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index document"}


class TestIndexFileErrors:
    """Tests for POST /api/v1/search/index/file."""

    def test_missing_body_returns_400(self, client):
        """An empty file payload is rejected before touching the index."""
        response = client.post("/api/v1/search/index/file", content_type="application/json")

        assert response.status_code == 400

    def test_null_body_returns_400(self, client):
        """A JSON ``null`` body is treated as a missing payload."""
        response = client.post(
            "/api/v1/search/index/file", data="null", content_type="application/json"
        )

        assert response.status_code == 400
        assert response.get_json() == {"error": "Request body is required"}

    def test_missing_id_returns_400(self, client):
        """A file without an id cannot be indexed."""
        response = client.post("/api/v1/search/index/file", json={"name": "a.txt"})

        assert response.status_code == 400
        assert "id" in response.get_json()["error"]

    def test_backend_failure_returns_500(self, client):
        """An unexpected indexing failure is reported as a 500."""
        with patch.object(Indexer, "index_file", side_effect=RuntimeError("boom")):
            response = client.post(
                "/api/v1/search/index/file", json={"id": "f-1", "name": "a.txt"}
            )

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index file"}


class TestIndexDocumentNullBody:
    """Tests for POST /api/v1/search/index/document with no payload."""

    def test_null_body_returns_400(self, client):
        """A JSON ``null`` body is treated as a missing payload."""
        response = client.post(
            "/api/v1/search/index/document", data="null", content_type="application/json"
        )

        assert response.status_code == 400
        assert response.get_json() == {"error": "Request body is required"}


class TestRemoveFromIndexErrors:
    """Tests for DELETE /api/v1/search/index/<type>/<id>."""

    def test_missing_document_returns_404(self, client, mock_meilisearch_client):
        """Removing something absent from the index returns 404."""
        import meilisearch
        from requests import Response

        response_stub = Response()
        response_stub.status_code = 404
        response_stub._content = b""
        mock_meilisearch_client.index.return_value.get_document.side_effect = (
            meilisearch.errors.MeilisearchApiError("missing", response_stub)
        )

        response = client.delete("/api/v1/search/index/document/nope")

        assert response.status_code == 404
        assert response.get_json()["status"] == "not_found"

    def test_backend_failure_returns_500(self, client):
        """An unexpected deletion failure is reported as a 500."""
        with patch.object(Indexer, "remove", side_effect=RuntimeError("boom")):
            response = client.delete("/api/v1/search/index/document/d-1")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to remove from index"}


class TestReindexErrors:
    """Tests for POST /api/v1/search/reindex."""

    def test_backend_failure_returns_500(self, client):
        """A failed reindex is reported as a 500."""
        with patch.object(Indexer, "reindex", side_effect=RuntimeError("boom")):
            response = client.post("/api/v1/search/reindex")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to reindex"}
