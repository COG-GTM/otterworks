"""Tests for error handling in the indexing API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def indexer() -> MagicMock:
    """Replace the per-request Indexer with a mock."""
    with patch("app.api.index._get_indexer") as factory:
        mock = MagicMock()
        factory.return_value = mock
        yield mock


class TestEmptyBodies:
    """An empty JSON object is rejected before the indexer is reached."""

    @pytest.mark.parametrize(
        "path", ["/api/v1/search/index/document", "/api/v1/search/index/file"]
    )
    def test_empty_json_object_returns_400(self, client, indexer, path):
        """POST {} is a client error, not an index write."""
        response = client.post(path, json={})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Request body is required"}
        indexer.index_document.assert_not_called()
        indexer.index_file.assert_not_called()


class TestIndexDocumentFailures:
    """Failure modes of POST /index/document."""

    def test_validation_error_is_surfaced_as_400(self, client, indexer):
        """A ValueError from the indexer becomes a 400 with its message."""
        indexer.index_document.side_effect = ValueError("Document 'title' is required")

        response = client.post("/api/v1/search/index/document", json={"id": "doc-1"})

        assert response.status_code == 400
        assert response.get_json() == {"error": "Document 'title' is required"}

    def test_unexpected_error_is_surfaced_as_500(self, client, indexer):
        """An unexpected backend failure is masked behind a generic 500."""
        indexer.index_document.side_effect = RuntimeError("meilisearch down")

        response = client.post(
            "/api/v1/search/index/document", json={"id": "doc-1", "title": "Doc"}
        )

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index document"}


class TestIndexFileFailures:
    """Failure modes of POST /index/file."""

    def test_validation_error_is_surfaced_as_400(self, client, indexer):
        """A ValueError from the indexer becomes a 400 with its message."""
        indexer.index_file.side_effect = ValueError("File 'name' is required")

        response = client.post("/api/v1/search/index/file", json={"id": "file-1"})

        assert response.status_code == 400
        assert response.get_json() == {"error": "File 'name' is required"}

    def test_unexpected_error_is_surfaced_as_500(self, client, indexer):
        """An unexpected backend failure is masked behind a generic 500."""
        indexer.index_file.side_effect = RuntimeError("meilisearch down")

        response = client.post(
            "/api/v1/search/index/file", json={"id": "file-1", "name": "a.txt"}
        )

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index file"}


class TestRemoveFromIndex:
    """Failure modes of DELETE /index/<type>/<id>."""

    def test_missing_document_returns_404(self, client, indexer):
        """A not_found result from the indexer maps to 404."""
        indexer.remove.return_value = {"status": "not_found", "id": "d-1", "type": "document"}

        response = client.delete("/api/v1/search/index/document/d-1")

        assert response.status_code == 404
        assert response.get_json()["status"] == "not_found"

    def test_invalid_type_returns_400(self, client, indexer):
        """An unsupported doc type is a client error."""
        indexer.remove.side_effect = ValueError("Invalid type 'widget'.")

        response = client.delete("/api/v1/search/index/widget/w-1")

        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid type 'widget'."}

    def test_unexpected_error_returns_500(self, client, indexer):
        """An unexpected backend failure is masked behind a generic 500."""
        indexer.remove.side_effect = RuntimeError("meilisearch down")

        response = client.delete("/api/v1/search/index/document/d-1")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to remove from index"}


class TestReindex:
    """Behaviour of POST /reindex."""

    def test_successful_reindex_returns_the_indexer_result(self, client, indexer):
        """The indexer's summary is passed through with a 200."""
        indexer.reindex.return_value = {
            "status": "reindexed",
            "indexed_counts": {"documents": 2, "files": 3},
        }

        response = client.post("/api/v1/search/reindex")

        assert response.status_code == 200
        assert response.get_json()["indexed_counts"] == {"documents": 2, "files": 3}

    def test_failed_reindex_returns_500(self, client, indexer):
        """A crash mid-reindex is reported as a server error."""
        indexer.reindex.side_effect = RuntimeError("document-service unreachable")

        response = client.post("/api/v1/search/reindex")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to reindex"}
