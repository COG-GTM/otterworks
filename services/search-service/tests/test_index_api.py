"""Tests for indexing API endpoints."""

from __future__ import annotations

from unittest.mock import patch

from app.services.indexer import ReindexSourceError
from tests.conftest import SERVICE_HEADERS, USER_HEADERS, USER_ID


class TestIndexDocumentEndpoint:
    """Tests for POST /api/v1/search/index/document."""

    def test_index_document_success(self, client, mock_meilisearch_client):
        """Index a valid document returns 201."""
        response = client.post(
            "/api/v1/search/index/document",
            headers=USER_HEADERS,
            json={
                "id": "doc-123",
                "title": "My Document",
                "content": "Document body text",
                "owner_id": "user-1",
                "tags": ["work"],
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "indexed"
        assert data["id"] == "doc-123"
        assert data["type"] == "document"

    def test_index_document_missing_body(self, client):
        """Index with empty body returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            headers=USER_HEADERS,
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_index_document_missing_id(self, client, mock_meilisearch_client):
        """Index document without id returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            headers=USER_HEADERS,
            json={"title": "No ID Doc"},
        )
        assert response.status_code == 400

    def test_index_document_missing_title(self, client, mock_meilisearch_client):
        """Index document without title returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            headers=USER_HEADERS,
            json={"id": "doc-no-title"},
        )
        assert response.status_code == 400


class TestIndexFileEndpoint:
    """Tests for POST /api/v1/search/index/file."""

    def test_index_file_success(self, client, mock_meilisearch_client):
        """Index a valid file returns 201."""
        response = client.post(
            "/api/v1/search/index/file",
            headers=USER_HEADERS,
            json={
                "id": "file-123",
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "owner_id": "user-1",
                "folder_id": "folder-1",
                "tags": ["report"],
                "size": 1024,
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "indexed"
        assert data["id"] == "file-123"
        assert data["type"] == "file"

    def test_index_file_missing_name(self, client, mock_meilisearch_client):
        """Index file without name returns 400."""
        response = client.post(
            "/api/v1/search/index/file",
            headers=USER_HEADERS,
            json={"id": "file-no-name"},
        )
        assert response.status_code == 400


class TestDeleteFromIndexEndpoint:
    """Tests for DELETE /api/v1/search/index/{type}/{id}."""

    def test_delete_document(self, client, mock_meilisearch_client):
        """Delete a document from index returns 200."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.get_document.side_effect = None
        mock_index.get_document.return_value = {"id": "doc-123", "owner_id": USER_ID}
        response = client.delete("/api/v1/search/index/document/doc-123", headers=USER_HEADERS)
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "deleted"

    def test_delete_invalid_type(self, client, mock_meilisearch_client):
        """Delete with invalid type returns 400."""
        response = client.delete("/api/v1/search/index/invalid/doc-123", headers=USER_HEADERS)
        assert response.status_code == 400


class TestReindexEndpoint:
    """Tests for POST /api/v1/search/reindex."""

    def test_reindex_success(self, client, mock_meilisearch_client):
        """Reindex returns 200."""
        with (
            patch("app.services.indexer.Indexer._fetch_all_documents", return_value=[]),
            patch("app.services.indexer.Indexer._fetch_all_files", return_value=[]),
        ):
            response = client.post("/api/v1/search/reindex", headers=SERVICE_HEADERS)
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "reindexed"


def _existing(mock_meilisearch_client, owner_id):
    mock_index = mock_meilisearch_client.index.return_value
    mock_index.get_document.side_effect = None
    mock_index.get_document.return_value = {"id": "doc-123", "owner_id": owner_id}
    return mock_index


class TestIndexAuthorization:
    """Index mutations are authorized even with REQUIRE_AUTH=false."""

    def test_index_without_identity_is_rejected(self, client, mock_meilisearch_client):
        response = client.post("/api/v1/search/index/document", json={"id": "d", "title": "t"})
        assert response.status_code == 401
        mock_meilisearch_client.index.return_value.add_documents.assert_not_called()

    def test_index_with_wrong_service_token_is_rejected(self, client, mock_meilisearch_client):
        response = client.post(
            "/api/v1/search/index/file",
            headers={"Authorization": "Bearer wrong"},
            json={"id": "f", "name": "n"},
        )
        assert response.status_code == 401
        mock_meilisearch_client.index.return_value.add_documents.assert_not_called()

    def test_user_cannot_index_for_another_owner(self, client, mock_meilisearch_client):
        response = client.post(
            "/api/v1/search/index/document",
            headers=USER_HEADERS,
            json={"id": "doc-x", "title": "Planted", "owner_id": "victim"},
        )
        assert response.status_code == 403
        mock_meilisearch_client.index.return_value.add_documents.assert_not_called()

    def test_user_cannot_index_file_for_another_owner(self, client, mock_meilisearch_client):
        response = client.post(
            "/api/v1/search/index/file",
            headers=USER_HEADERS,
            json={"id": "file-x", "name": "planted.pdf", "owner_id": "victim"},
        )
        assert response.status_code == 403
        mock_meilisearch_client.index.return_value.add_documents.assert_not_called()

    def test_owner_is_bound_to_caller_when_omitted(self, client, mock_meilisearch_client):
        response = client.post(
            "/api/v1/search/index/document",
            headers=USER_HEADERS,
            json={"id": "doc-new", "title": "Mine"},
        )
        assert response.status_code == 201
        added = mock_meilisearch_client.index.return_value.add_documents.call_args[0][0][0]
        assert added["owner_id"] == USER_ID

    def test_user_cannot_overwrite_another_users_entry(self, client, mock_meilisearch_client):
        mock_index = _existing(mock_meilisearch_client, "victim")
        response = client.post(
            "/api/v1/search/index/document",
            headers=USER_HEADERS,
            json={"id": "doc-123", "title": "Overwrite", "owner_id": USER_ID},
        )
        assert response.status_code == 403
        mock_index.add_documents.assert_not_called()

    def test_user_can_update_own_entry(self, client, mock_meilisearch_client):
        mock_index = _existing(mock_meilisearch_client, USER_ID)
        response = client.post(
            "/api/v1/search/index/document",
            headers=USER_HEADERS,
            json={"id": "doc-123", "title": "Updated"},
        )
        assert response.status_code == 201
        mock_index.add_documents.assert_called_once()

    def test_service_token_can_index_for_any_owner(self, client, mock_meilisearch_client):
        mock_index = _existing(mock_meilisearch_client, "someone")
        response = client.post(
            "/api/v1/search/index/document",
            headers=SERVICE_HEADERS,
            json={"id": "doc-123", "title": "From SQS", "owner_id": "someone-else"},
        )
        assert response.status_code == 201
        assert mock_index.add_documents.call_args[0][0][0]["owner_id"] == "someone-else"

    def test_delete_without_identity_is_rejected(self, client, mock_meilisearch_client):
        mock_index = _existing(mock_meilisearch_client, USER_ID)
        response = client.delete("/api/v1/search/index/document/doc-123")
        assert response.status_code == 401
        mock_index.delete_document.assert_not_called()

    def test_user_cannot_delete_another_users_entry(self, client, mock_meilisearch_client):
        mock_index = _existing(mock_meilisearch_client, "victim")
        response = client.delete("/api/v1/search/index/document/doc-123", headers=USER_HEADERS)
        assert response.status_code == 404
        mock_index.delete_document.assert_not_called()

    def test_delete_missing_entry_returns_404(self, client, mock_meilisearch_client):
        response = client.delete("/api/v1/search/index/file/nope", headers=USER_HEADERS)
        assert response.status_code == 404
        mock_meilisearch_client.index.return_value.delete_document.assert_not_called()

    def test_service_token_can_delete_any_entry(self, client, mock_meilisearch_client):
        mock_index = _existing(mock_meilisearch_client, "victim")
        response = client.delete("/api/v1/search/index/document/doc-123", headers=SERVICE_HEADERS)
        assert response.status_code == 200
        mock_index.delete_document.assert_called_once_with("doc-123")


class TestReindexAuthorization:
    """Reindex is restricted to the service token and fails closed."""

    def test_reindex_without_identity_is_rejected(self, client, mock_meilisearch_client):
        response = client.post("/api/v1/search/reindex")
        assert response.status_code == 401
        mock_meilisearch_client.delete_index.assert_not_called()

    def test_reindex_as_user_is_forbidden(self, client, mock_meilisearch_client):
        response = client.post("/api/v1/search/reindex", headers=USER_HEADERS)
        assert response.status_code == 403
        mock_meilisearch_client.delete_index.assert_not_called()

    def test_reindex_with_wrong_token_is_rejected(self, client, mock_meilisearch_client):
        response = client.post(
            "/api/v1/search/reindex",
            headers={"Authorization": "Bearer wrong", **USER_HEADERS},
        )
        assert response.status_code == 403
        mock_meilisearch_client.delete_index.assert_not_called()

    def test_reindex_source_failure_keeps_indices(self, client, mock_meilisearch_client):
        with patch(
            "app.services.indexer.Indexer._fetch_all_documents",
            side_effect=ReindexSourceError("document-service returned 401"),
        ):
            response = client.post("/api/v1/search/reindex", headers=SERVICE_HEADERS)
        assert response.status_code == 502
        mock_meilisearch_client.delete_index.assert_not_called()
