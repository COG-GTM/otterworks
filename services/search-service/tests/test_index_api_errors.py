"""Tests for the error paths of the indexing API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def indexer() -> MagicMock:
    """Replace the Indexer constructed per request with a mock."""
    mock = MagicMock()
    with patch("app.api.index.Indexer", return_value=mock):
        yield mock


class TestIndexDocumentErrors:
    """Tests for POST /api/v1/search/index/document."""

    def test_empty_json_object_returns_400(self, client):
        response = client.post("/api/v1/search/index/document", json={})

        assert response.status_code == 400
        assert response.get_json()["error"] == "Request body is required"

    def test_unexpected_failure_returns_500(self, client, indexer):
        indexer.index_document.side_effect = RuntimeError("meilisearch down")

        response = client.post(
            "/api/v1/search/index/document", json={"id": "d-1", "title": "One"}
        )

        assert response.status_code == 500
        assert response.get_json()["error"] == "Failed to index document"


class TestIndexFileErrors:
    """Tests for POST /api/v1/search/index/file."""

    def test_empty_json_object_returns_400(self, client):
        response = client.post("/api/v1/search/index/file", json={})

        assert response.status_code == 400
        assert response.get_json()["error"] == "Request body is required"

    def test_unexpected_failure_returns_500(self, client, indexer):
        indexer.index_file.side_effect = RuntimeError("meilisearch down")

        response = client.post(
            "/api/v1/search/index/file", json={"id": "f-1", "name": "a.txt"}
        )

        assert response.status_code == 500
        assert response.get_json()["error"] == "Failed to index file"


class TestRemoveFromIndexErrors:
    """Tests for DELETE /api/v1/search/index/<type>/<id>."""

    def test_unknown_id_returns_404(self, client, indexer):
        indexer.remove.return_value = {"status": "not_found", "id": "d-1", "type": "document"}

        response = client.delete("/api/v1/search/index/document/d-1")

        assert response.status_code == 404
        assert response.get_json()["status"] == "not_found"

    def test_invalid_type_returns_400(self, client, indexer):
        indexer.remove.side_effect = ValueError("Invalid type 'widget'.")

        response = client.delete("/api/v1/search/index/widget/d-1")

        assert response.status_code == 400
        assert response.get_json()["error"] == "Invalid type 'widget'."

    def test_unexpected_failure_returns_500(self, client, indexer):
        indexer.remove.side_effect = RuntimeError("meilisearch down")

        response = client.delete("/api/v1/search/index/document/d-1")

        assert response.status_code == 500
        assert response.get_json()["error"] == "Failed to remove from index"


class TestReindexErrors:
    """Tests for POST /api/v1/search/reindex."""

    def test_unexpected_failure_returns_500(self, client, indexer):
        indexer.reindex.side_effect = RuntimeError("document-service unreachable")

        response = client.post("/api/v1/search/reindex")

        assert response.status_code == 500
        assert response.get_json()["error"] == "Failed to reindex"
