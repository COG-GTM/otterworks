"""Tests for the authentication middleware."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, AuthConfig
from app.main import create_app

SERVICE_TOKEN = "s2s-token"


def _client(app_config: AppConfig, mock_client: MagicMock, auth: AuthConfig):
    """Build a test client for an app configured with *auth*."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_client
        flask_app = create_app(replace(app_config, auth=auth))
        flask_app.config["TESTING"] = True
        return flask_app.test_client()


@pytest.fixture()
def authed_client(app_config: AppConfig, mock_meilisearch_client: MagicMock):
    """A client for an app that enforces auth and has a service token."""
    return _client(
        app_config,
        mock_meilisearch_client,
        AuthConfig(service_token=SERVICE_TOKEN, require_auth=True),
    )


@pytest.fixture()
def gateway_only_client(app_config: AppConfig, mock_meilisearch_client: MagicMock):
    """A client for an app that enforces auth with no service token configured."""
    return _client(
        app_config,
        mock_meilisearch_client,
        AuthConfig(service_token="", require_auth=True),
    )


class TestPublicEndpoints:
    """Health and metrics stay reachable without credentials."""

    @pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
    def test_public_paths_do_not_require_auth(self, authed_client, path):
        assert authed_client.get(path).status_code in (200, 503)


class TestProtectedEndpoints:
    """Everything else needs a service token or a gateway identity."""

    def test_request_without_credentials_is_rejected(self, authed_client):
        response = authed_client.get("/api/v1/search/?q=hello")

        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}

    def test_unknown_path_without_credentials_is_rejected(self, authed_client):
        """Auth runs before routing, so 404 paths are rejected too."""
        assert authed_client.get("/api/v1/nope").status_code == 401

    def test_valid_service_token_is_accepted(self, authed_client):
        response = authed_client.get(
            "/api/v1/search/?q=hello",
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        )

        assert response.status_code == 200

    def test_bearer_scheme_is_case_insensitive(self, authed_client):
        response = authed_client.get(
            "/api/v1/search/?q=hello",
            headers={"Authorization": f"bearer {SERVICE_TOKEN}"},
        )

        assert response.status_code == 200

    def test_wrong_service_token_is_rejected(self, authed_client):
        response = authed_client.get(
            "/api/v1/search/?q=hello", headers={"Authorization": "Bearer nope"}
        )

        assert response.status_code == 401

    def test_non_bearer_authorization_header_is_rejected(self, authed_client):
        response = authed_client.get(
            "/api/v1/search/?q=hello", headers={"Authorization": "Basic abc123"}
        )

        assert response.status_code == 401

    def test_gateway_user_header_is_accepted(self, authed_client):
        response = authed_client.get(
            "/api/v1/search/?q=hello", headers={"X-User-ID": "user-1"}
        )

        assert response.status_code == 200

    def test_blank_gateway_user_header_is_rejected(self, authed_client):
        response = authed_client.get(
            "/api/v1/search/?q=hello", headers={"X-User-ID": "   "}
        )

        assert response.status_code == 401

    def test_gateway_identity_is_the_only_path_without_a_service_token(
        self, gateway_only_client
    ):
        """With no token configured, a bearer header cannot authenticate."""
        rejected = gateway_only_client.get(
            "/api/v1/search/?q=hello", headers={"Authorization": "Bearer anything"}
        )
        accepted = gateway_only_client.get(
            "/api/v1/search/?q=hello", headers={"X-User-ID": "user-1"}
        )

        assert rejected.status_code == 401
        assert accepted.status_code == 200


class TestAuthDisabled:
    """When require_auth is off the hook short-circuits."""

    def test_anonymous_request_is_allowed(self, client):
        assert client.get("/api/v1/search/?q=hello").status_code == 200
