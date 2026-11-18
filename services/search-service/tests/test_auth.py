"""Tests for the authentication middleware."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from app.config import AuthConfig
from app.main import create_app

SEARCH_URL = "/api/v1/search/analytics"


def _make_client(app_config, mock_meilisearch_client, service_token: str):
    config = replace(app_config, auth=AuthConfig(service_token=service_token, require_auth=True))
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture()
def auth_client(app_config, mock_meilisearch_client):
    return _make_client(app_config, mock_meilisearch_client, "secret-token")


@pytest.fixture()
def no_token_client(app_config, mock_meilisearch_client):
    return _make_client(app_config, mock_meilisearch_client, "")


class TestAuthMiddleware:
    @pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
    def test_public_paths_bypass_auth(self, auth_client, path):
        assert auth_client.get(path).status_code in (200, 503)

    def test_missing_credentials_rejected(self, auth_client):
        response = auth_client.get(SEARCH_URL)
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}

    def test_valid_service_token_accepted(self, auth_client):
        response = auth_client.get(SEARCH_URL, headers={"Authorization": "Bearer secret-token"})
        assert response.status_code == 200

    def test_bearer_scheme_is_case_insensitive(self, auth_client):
        response = auth_client.get(SEARCH_URL, headers={"Authorization": "bearer   secret-token  "})
        assert response.status_code == 200

    def test_wrong_service_token_rejected(self, auth_client):
        response = auth_client.get(SEARCH_URL, headers={"Authorization": "Bearer nope"})
        assert response.status_code == 401

    def test_non_bearer_scheme_rejected(self, auth_client):
        response = auth_client.get(SEARCH_URL, headers={"Authorization": "Basic secret-token"})
        assert response.status_code == 401

    def test_empty_bearer_rejected(self, auth_client):
        response = auth_client.get(SEARCH_URL, headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_gateway_user_header_accepted(self, auth_client):
        response = auth_client.get(SEARCH_URL, headers={"X-User-ID": "user-1"})
        assert response.status_code == 200

    def test_blank_gateway_user_header_rejected(self, auth_client):
        response = auth_client.get(SEARCH_URL, headers={"X-User-ID": "   "})
        assert response.status_code == 401

    def test_token_ignored_when_not_configured(self, no_token_client):
        response = no_token_client.get(SEARCH_URL, headers={"Authorization": "Bearer "})
        assert response.status_code == 401
        response = no_token_client.get(SEARCH_URL, headers={"Authorization": "Bearer anything"})
        assert response.status_code == 401

    def test_gateway_header_works_without_token_configured(self, no_token_client):
        response = no_token_client.get(SEARCH_URL, headers={"X-User-ID": "user-1"})
        assert response.status_code == 200

    def test_unknown_route_rejected_before_routing(self, auth_client):
        assert auth_client.get("/does-not-exist").status_code == 401

    def test_write_endpoints_require_auth(self, auth_client):
        assert auth_client.post("/api/v1/search/reindex").status_code == 401
        assert auth_client.delete("/api/v1/search/index/document/doc-1").status_code == 401
