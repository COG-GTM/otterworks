"""Tests for indexing API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.config import AppConfig, AuthConfig
from app.main import create_app


def _empty_page() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"items": []}
    return resp


class TestIndexDocumentEndpoint:
    """Tests for POST /api/v1/search/index/document."""

    def test_index_document_success(self, client, mock_meilisearch_client, service_headers):
        """Index a valid document returns 201."""
        response = client.post(
            "/api/v1/search/index/document",
            headers=service_headers,
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

    def test_index_document_missing_body(self, client, service_headers):
        """Index with empty body returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            headers=service_headers,
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_index_document_missing_id(self, client, mock_meilisearch_client, service_headers):
        """Index document without id returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            headers=service_headers,
            json={"title": "No ID Doc"},
        )
        assert response.status_code == 400

    def test_index_document_missing_title(self, client, mock_meilisearch_client, service_headers):
        """Index document without title returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            headers=service_headers,
            json={"id": "doc-no-title"},
        )
        assert response.status_code == 400


class TestIndexFileEndpoint:
    """Tests for POST /api/v1/search/index/file."""

    def test_index_file_success(self, client, mock_meilisearch_client, service_headers):
        """Index a valid file returns 201."""
        response = client.post(
            "/api/v1/search/index/file",
            headers=service_headers,
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

    def test_index_file_missing_name(self, client, mock_meilisearch_client, service_headers):
        """Index file without name returns 400."""
        response = client.post(
            "/api/v1/search/index/file",
            headers=service_headers,
            json={"id": "file-no-name"},
        )
        assert response.status_code == 400


class TestDeleteFromIndexEndpoint:
    """Tests for DELETE /api/v1/search/index/{type}/{id}."""

    def test_delete_document(self, client, mock_meilisearch_client, service_headers):
        """Delete a document from index returns 200."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.get_document.return_value = {"id": "doc-123"}
        response = client.delete("/api/v1/search/index/document/doc-123", headers=service_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "deleted"

    def test_delete_invalid_type(self, client, mock_meilisearch_client, service_headers):
        """Delete with invalid type returns 400."""
        response = client.delete("/api/v1/search/index/invalid/doc-123", headers=service_headers)
        assert response.status_code == 400


class TestReindexEndpoint:
    """Tests for POST /api/v1/search/reindex."""

    def test_reindex_success(self, client, mock_meilisearch_client, service_headers):
        """Reindex returns 200."""
        with patch("app.services.indexer.requests.get", return_value=_empty_page()):
            response = client.post("/api/v1/search/reindex", headers=service_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "reindexed"

    def test_reindex_aborts_without_wiping_when_source_unreachable(
        self, client, mock_meilisearch_client, service_headers
    ):
        """A failed crawl returns 502 and leaves the existing indices intact."""
        with patch(
            "app.services.indexer.requests.get",
            side_effect=requests.ConnectionError("document-service down"),
        ):
            response = client.post("/api/v1/search/reindex", headers=service_headers)
        assert response.status_code == 502
        mock_meilisearch_client.delete_index.assert_not_called()


MUTATIONS = [
    ("post", "/api/v1/search/index/document", {"id": "doc-victim", "title": "Forged", "owner_id": "victim"}),
    ("post", "/api/v1/search/index/file", {"id": "file-victim", "name": "forged.pdf", "owner_id": "victim"}),
    ("delete", "/api/v1/search/index/document/doc-victim", None),
    ("delete", "/api/v1/search/index/file/file-victim", None),
    ("post", "/api/v1/search/reindex", None),
]


def _assert_index_untouched(mock_client: MagicMock) -> None:
    mock_index = mock_client.index.return_value
    mock_index.add_documents.assert_not_called()
    mock_index.delete_document.assert_not_called()
    mock_client.delete_index.assert_not_called()


def _send(client, method, path, body, headers):
    if body is None:
        return getattr(client, method)(path, headers=headers)
    return getattr(client, method)(path, json=body, headers=headers)


class TestIndexMutationAuthorization:
    """Index mutations are internal: only the service token may call them."""

    @pytest.mark.parametrize(("method", "path", "body"), MUTATIONS)
    def test_gateway_user_is_forbidden(self, client, mock_meilisearch_client, method, path, body):
        response = _send(client, method, path, body, {"X-User-ID": "attacker"})
        assert response.status_code == 403
        _assert_index_untouched(mock_meilisearch_client)

    @pytest.mark.parametrize(("method", "path", "body"), MUTATIONS)
    def test_wrong_bearer_is_forbidden(self, client, mock_meilisearch_client, method, path, body):
        response = _send(client, method, path, body, {"Authorization": "Bearer user-jwt"})
        assert response.status_code == 403
        _assert_index_untouched(mock_meilisearch_client)

    @pytest.mark.parametrize(("method", "path", "body"), MUTATIONS)
    def test_anonymous_is_unauthorized(self, client, mock_meilisearch_client, method, path, body):
        response = _send(client, method, path, body, {})
        assert response.status_code == 401
        _assert_index_untouched(mock_meilisearch_client)

    @pytest.mark.parametrize(("method", "path", "body"), MUTATIONS)
    def test_closed_when_service_token_unset(
        self, app_config, mock_meilisearch_client, method, path, body
    ):
        config = AppConfig(
            meilisearch=app_config.meilisearch,
            sqs=app_config.sqs,
            auth=AuthConfig(service_token="", require_auth=True),
        )
        with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
            mock_cls.return_value = mock_meilisearch_client
            unconfigured = create_app(config).test_client()
        for headers in ({}, {"X-User-ID": "attacker"}, {"Authorization": "Bearer "}):
            response = _send(unconfigured, method, path, body, headers)
            assert response.status_code in (401, 403)
        _assert_index_untouched(mock_meilisearch_client)

    @pytest.mark.parametrize(("method", "path", "body"), MUTATIONS)
    def test_gateway_user_forbidden_with_require_auth_enabled(
        self, app_config, mock_meilisearch_client, method, path, body
    ):
        # Deployed default: X-User-ID satisfies require_auth, but not the index routes.
        config = AppConfig(
            meilisearch=app_config.meilisearch,
            sqs=app_config.sqs,
            auth=AuthConfig(service_token=app_config.auth.service_token, require_auth=True),
        )
        with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
            mock_cls.return_value = mock_meilisearch_client
            gateway_client = create_app(config).test_client()
        response = _send(gateway_client, method, path, body, {"X-User-ID": "attacker"})
        assert response.status_code == 403
        _assert_index_untouched(mock_meilisearch_client)
        search = gateway_client.get("/api/v1/search/?q=report", headers={"X-User-ID": "attacker"})
        assert search.status_code == 200

    def test_search_still_open_to_gateway_users(self, client, mock_meilisearch_client):
        response = client.get("/api/v1/search/?q=report", headers={"X-User-ID": "user-1"})
        assert response.status_code == 200
