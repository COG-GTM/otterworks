"""Tests for the CSRF guard on state-changing search-service requests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, AuthConfig, CSRFConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app

DOC = {"id": "doc-1", "title": "Quarterly plan", "owner_id": "user-1"}
ADVANCED = "/api/v1/search/advanced"
INDEX_DOC = "/api/v1/search/index/document"


class TestCrossSiteWritesRejected:
    def test_form_post_from_foreign_origin_rejected(self, client, mock_meilisearch_client):
        response = client.post(
            INDEX_DOC,
            data={"id": "doc-1", "title": "pwned"},
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code == 403
        assert response.get_json() == {"error": "csrf_rejected"}
        mock_meilisearch_client.index.return_value.add_documents.assert_not_called()

    def test_json_post_from_foreign_origin_rejected(self, client, mock_meilisearch_client):
        response = client.post(INDEX_DOC, json=DOC, headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        mock_meilisearch_client.index.return_value.add_documents.assert_not_called()

    def test_null_origin_rejected(self, client):
        response = client.post(ADVANCED, json={"q": "plan"}, headers={"Origin": "null"})
        assert response.status_code == 403

    def test_sibling_subdomain_origin_rejected(self, client):
        response = client.post(
            ADVANCED,
            json={"q": "plan"},
            headers={"Origin": "https://t-other.otterworks.app", "Host": "t-main.otterworks.app"},
        )
        assert response.status_code == 403

    def test_cross_site_fetch_without_origin_rejected(self, client):
        response = client.post(ADVANCED, json={"q": "plan"}, headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 403

    def test_cross_site_delete_rejected(self, client, mock_meilisearch_client):
        response = client.delete(
            "/api/v1/search/index/document/doc-1", headers={"Origin": "https://evil.example"}
        )
        assert response.status_code == 403
        mock_meilisearch_client.index.return_value.delete_document.assert_not_called()

    @pytest.mark.parametrize(
        "content_type",
        ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"],
    )
    def test_simple_request_content_types_rejected(self, client, mock_meilisearch_client, content_type):
        response = client.post(INDEX_DOC, data='{"id": "doc-1", "title": "x"}', content_type=content_type)
        assert response.status_code == 415
        assert response.get_json() == {"error": "unsupported_media_type"}
        mock_meilisearch_client.index.return_value.add_documents.assert_not_called()


class TestLegitimateWritesAllowed:
    def test_server_to_server_json_post(self, client):
        assert client.post(INDEX_DOC, json=DOC).status_code == 201

    def test_bodyless_post_and_delete(self, client):
        assert client.post("/api/v1/search/reindex").status_code == 200
        assert client.delete("/api/v1/search/index/document/doc-1").status_code == 200

    def test_trusted_origin(self, client):
        response = client.post(
            ADVANCED,
            json={"q": "plan"},
            headers={"Origin": "http://localhost:3000", "Sec-Fetch-Site": "same-site"},
        )
        assert response.status_code == 200

    def test_same_host_origin_behind_tls_terminating_proxy(self, client):
        response = client.post(
            ADVANCED,
            json={"q": "plan"},
            headers={
                "Origin": "https://t-main.otterworks.app",
                "Host": "t-main.otterworks.app",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        assert response.status_code == 200

    def test_desktop_loopback_origin_through_gateway_host(self, client):
        response = client.post(
            ADVANCED,
            json={"q": "plan"},
            headers={"Origin": "http://127.0.0.1:34117", "Host": "localhost:8080"},
        )
        assert response.status_code == 200

    def test_loopback_lookalike_host_rejected(self, client):
        response = client.post(
            ADVANCED,
            json={"q": "plan"},
            headers={"Origin": "http://localhost.evil.example", "Host": "t-main.otterworks.app"},
        )
        assert response.status_code == 403

    def test_json_with_charset(self, client):
        response = client.post(
            ADVANCED, data='{"q": "plan"}', content_type="application/json; charset=utf-8"
        )
        assert response.status_code == 200

    def test_safe_methods_unaffected(self, client):
        response = client.get(
            "/api/v1/search/?q=plan",
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code == 200


class TestCorsAndConfig:
    def test_cors_preflight_denied_for_foreign_origin(self, client):
        response = client.options(
            ADVANCED,
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "Access-Control-Allow-Origin" not in response.headers

    def test_cors_never_allows_credentials(self, client):
        response = client.options(
            ADVANCED,
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
        )
        assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
        assert "Access-Control-Allow-Credentials" not in response.headers

    def test_env_trusted_origins(self, monkeypatch):
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://cors.example")
        monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", " https://app.example:443 , https://b.example ")
        assert CSRFConfig().trusted_origins == ("https://app.example:443", "https://b.example")
        monkeypatch.delenv("CSRF_TRUSTED_ORIGINS")
        assert CSRFConfig().trusted_origins == ("https://cors.example",)

    def test_configured_origin_trusted_with_default_port(self, mock_meilisearch_client):
        config = AppConfig(
            meilisearch=MeiliSearchConfig(url="http://localhost:7700"),
            sqs=SQSConfig(enabled=False),
            auth=AuthConfig(service_token="", require_auth=False),
            csrf=CSRFConfig(trusted_origins=("https://app.example:443",)),
        )
        with patch("app.services.meilisearch_client.meilisearch.Client", return_value=mock_meilisearch_client):
            app = create_app(config)
        client = app.test_client()
        ok = client.post(ADVANCED, json={"q": "x"}, headers={"Origin": "https://app.example"})
        assert ok.status_code == 200
        preflight = client.options(
            ADVANCED,
            headers={"Origin": "https://app.example", "Access-Control-Request-Method": "POST"},
        )
        assert preflight.headers.get("Access-Control-Allow-Origin") == "https://app.example"
        bad = client.post(ADVANCED, json={"q": "x"}, headers={"Origin": "https://other.example"})
        assert bad.status_code == 403


class TestCsrfRunsBeforeAuth:
    def test_cross_site_with_service_token_still_rejected(self, mock_meilisearch_client: MagicMock):
        config = AppConfig(
            meilisearch=MeiliSearchConfig(url="http://localhost:7700"),
            sqs=SQSConfig(enabled=False),
            auth=AuthConfig(service_token="svc-token", require_auth=True),
        )
        with patch("app.services.meilisearch_client.meilisearch.Client", return_value=mock_meilisearch_client):
            app = create_app(config)
        client = app.test_client()
        headers = {"Authorization": "Bearer svc-token"}
        assert client.post(INDEX_DOC, json=DOC, headers=headers).status_code == 201
        headers["Origin"] = "https://evil.example"
        assert client.post(INDEX_DOC, json=DOC, headers=headers).status_code == 403
