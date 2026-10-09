"""Tests for indexing API endpoints."""

from __future__ import annotations

import pytest


class TestIndexDocumentEndpoint:
    """Tests for POST /api/v1/search/index/document."""

    def test_index_document_success(self, client, mock_meilisearch_client):
        """Index a valid document returns 201."""
        response = client.post(
            "/api/v1/search/index/document",
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
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_index_document_missing_id(self, client, mock_meilisearch_client):
        """Index document without id returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            json={"title": "No ID Doc"},
        )
        assert response.status_code == 400

    def test_index_document_missing_title(self, client, mock_meilisearch_client):
        """Index document without title returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            json={"id": "doc-no-title"},
        )
        assert response.status_code == 400


class TestIndexFileEndpoint:
    """Tests for POST /api/v1/search/index/file."""

    def test_index_file_success(self, client, mock_meilisearch_client):
        """Index a valid file returns 201."""
        response = client.post(
            "/api/v1/search/index/file",
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
            json={"id": "file-no-name"},
        )
        assert response.status_code == 400


class TestDeleteFromIndexEndpoint:
    """Tests for DELETE /api/v1/search/index/{type}/{id}."""

    def test_delete_document(self, client, mock_meilisearch_client):
        """Delete a document from index returns 200."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.get_document.return_value = {"id": "doc-123"}
        response = client.delete("/api/v1/search/index/document/doc-123")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "deleted"

    def test_delete_invalid_type(self, client, mock_meilisearch_client):
        """Delete with invalid type returns 400."""
        response = client.delete("/api/v1/search/index/invalid/doc-123")
        assert response.status_code == 400


class TestReindexEndpoint:
    """Tests for POST /api/v1/search/reindex."""

    @staticmethod
    def _client(app_config, mock_meilisearch_client, token):
        from dataclasses import replace
        from unittest.mock import patch

        from app.config import AuthConfig
        from app.main import create_app

        config = replace(app_config, auth=AuthConfig(service_token=token, require_auth=True))
        with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
            mock_cls.return_value = mock_meilisearch_client
            return create_app(config).test_client()

    def test_reindex_success(self, app_config, mock_meilisearch_client):
        """Reindex with the service token returns 200."""
        client = self._client(app_config, mock_meilisearch_client, "svc-token")
        response = client.post(
            "/api/v1/search/reindex", headers={"Authorization": "Bearer svc-token"}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "reindexed"

    @pytest.mark.parametrize(
        "headers",
        [
            {"X-User-ID": "user-1"},
            {"X-User-ID": "user-1", "Authorization": "Bearer wrong"},
            {},
        ],
    )
    def test_reindex_requires_service_token(self, app_config, mock_meilisearch_client, headers):
        """A gateway user identity alone cannot wipe and rebuild the index."""
        client = self._client(app_config, mock_meilisearch_client, "svc-token")
        response = client.post("/api/v1/search/reindex", headers=headers)
        assert response.status_code in (401, 403)
        mock_meilisearch_client.delete_index.assert_not_called()

    def test_reindex_refused_when_no_token_configured(self, client, mock_meilisearch_client):
        """With no service token configured (REQUIRE_AUTH off), reindex stays closed."""
        response = client.post("/api/v1/search/reindex", headers={"X-User-ID": "user-1"})
        assert response.status_code == 403
        mock_meilisearch_client.delete_index.assert_not_called()
