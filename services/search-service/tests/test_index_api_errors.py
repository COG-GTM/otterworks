"""Error paths of the indexing API blueprint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def indexer() -> MagicMock:
    """Patch the Indexer the blueprint builds per request."""
    with patch("app.api.index.Indexer") as indexer_cls:
        yield indexer_cls.return_value


class TestIndexDocumentErrors:
    """POST /api/v1/search/index/document."""

    def test_empty_body_returns_400(self, client):
        response = client.post("/api/v1/search/index/document", json={})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Request body is required"}

    def test_backend_failure_returns_500(self, client, indexer):
        indexer.index_document.side_effect = RuntimeError("meilisearch down")

        response = client.post("/api/v1/search/index/document", json={"id": "d-1", "title": "P"})

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index document"}


class TestIndexFileErrors:
    """POST /api/v1/search/index/file."""

    def test_empty_body_returns_400(self, client):
        response = client.post("/api/v1/search/index/file", json={})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Request body is required"}

    def test_missing_id_returns_400(self, client):
        response = client.post("/api/v1/search/index/file", json={"name": "report.pdf"})

        assert response.status_code == 400
        assert "id" in response.get_json()["error"]

    def test_backend_failure_returns_500(self, client, indexer):
        indexer.index_file.side_effect = RuntimeError("meilisearch down")

        response = client.post(
            "/api/v1/search/index/file", json={"id": "f-1", "name": "report.pdf"}
        )

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index file"}


class TestRemoveFromIndexErrors:
    """DELETE /api/v1/search/index/<type>/<id>."""

    def test_unknown_document_returns_404(self, client, indexer):
        indexer.remove.return_value = {"status": "not_found", "id": "d-9", "type": "document"}

        response = client.delete("/api/v1/search/index/document/d-9")

        assert response.status_code == 404
        assert response.get_json()["status"] == "not_found"

    def test_backend_failure_returns_500(self, client, indexer):
        indexer.remove.side_effect = RuntimeError("meilisearch down")

        response = client.delete("/api/v1/search/index/document/d-1")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to remove from index"}


class TestReindexErrors:
    """POST /api/v1/search/reindex."""

    def test_backend_failure_returns_500(self, client, indexer):
        indexer.reindex.side_effect = RuntimeError("meilisearch down")

        response = client.post("/api/v1/search/reindex")

        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to reindex"}

    def test_success_returns_the_indexer_result(self, client, indexer):
        indexer.reindex.return_value = {"status": "reindexed", "indices": ["documents"]}

        response = client.post("/api/v1/search/reindex")

        assert response.status_code == 200
        assert response.get_json()["status"] == "reindexed"
