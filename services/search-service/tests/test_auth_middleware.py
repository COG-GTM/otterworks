"""Tests for the authentication middleware.

The shared ``app`` fixture disables auth, so these tests build their own apps
with ``require_auth`` enabled.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app
from app.middleware.auth import _extract_bearer_token

SERVICE_TOKEN = "svc-token"


def _config(service_token: str, require_auth: bool = True) -> AppConfig:
    return AppConfig(
        service_name="search-service-test",
        port=8087,
        debug=True,
        log_level="DEBUG",
        meilisearch=MeiliSearchConfig(
            url="http://localhost:7700",
            api_key="",
            documents_index="test-otterworks-documents",
            files_index="test-otterworks-files",
        ),
        sqs=SQSConfig(enabled=False),
        auth=AuthConfig(service_token=service_token, require_auth=require_auth),
    )


def _client(config: AppConfig, mock_meilisearch_client: MagicMock):
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture()
def secured_client(mock_meilisearch_client: MagicMock):
    """Client for an app that requires auth and has a service token configured."""
    return _client(_config(SERVICE_TOKEN), mock_meilisearch_client)


@pytest.fixture()
def gateway_only_client(mock_meilisearch_client: MagicMock):
    """Client for an app that requires auth but has no service token configured."""
    return _client(_config(""), mock_meilisearch_client)


class TestPublicEndpoints:
    """Health and metrics are always reachable."""

    @pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
    def test_public_paths_do_not_require_auth(self, secured_client, path):
        response = secured_client.get(path)
        assert response.status_code != 401


class TestServiceToken:
    """Trusted internal callers authenticate with the service token."""

    def test_valid_bearer_token_is_accepted(self, secured_client):
        response = secured_client.post(
            "/api/v1/search/index/document",
            json={"id": "d-1", "title": "Plan"},
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        )
        assert response.status_code == 201

    def test_token_matching_is_case_insensitive_on_the_scheme(self, secured_client):
        response = secured_client.get(
            "/api/v1/search/analytics",
            headers={"Authorization": f"bearer {SERVICE_TOKEN}"},
        )
        assert response.status_code == 200

    def test_wrong_token_without_gateway_identity_is_rejected(self, secured_client):
        response = secured_client.get(
            "/api/v1/search/analytics", headers={"Authorization": "Bearer nope"}
        )
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}

    def test_wrong_token_with_gateway_identity_is_accepted(self, secured_client):
        response = secured_client.get(
            "/api/v1/search/analytics",
            headers={"Authorization": "Bearer nope", "X-User-ID": "user-1"},
        )
        assert response.status_code == 200


class TestGatewayIdentity:
    """Without a service token only the gateway identity path is available."""

    def test_missing_credentials_are_rejected(self, gateway_only_client):
        response = gateway_only_client.get("/api/v1/search/analytics")
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}

    def test_blank_user_id_header_is_rejected(self, gateway_only_client):
        response = gateway_only_client.get(
            "/api/v1/search/analytics", headers={"X-User-ID": "   "}
        )
        assert response.status_code == 401

    def test_user_id_header_is_accepted(self, gateway_only_client):
        response = gateway_only_client.get(
            "/api/v1/search/analytics", headers={"X-User-ID": "user-1"}
        )
        assert response.status_code == 200

    def test_service_token_is_ignored_when_none_is_configured(self, gateway_only_client):
        response = gateway_only_client.get(
            "/api/v1/search/analytics", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}
        )
        assert response.status_code == 401


class TestAuthDisabled:
    """require_auth=false lets every request through."""

    def test_unauthenticated_request_is_allowed(self, mock_meilisearch_client):
        client = _client(_config(SERVICE_TOKEN, require_auth=False), mock_meilisearch_client)
        assert client.get("/api/v1/search/analytics").status_code == 200


class TestExtractBearerToken:
    """_extract_bearer_token parses the Authorization header."""

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("Bearer abc123", "abc123"),
            ("bearer abc123", "abc123"),
            ("BEARER   abc123  ", "abc123"),
            ("Basic abc123", ""),
            ("abc123", ""),
            ("", ""),
        ],
    )
    def test_parses_supported_header_forms(self, app, header, expected):
        with app.test_request_context("/", headers={"Authorization": header}):
            assert _extract_bearer_token() == expected

    def test_returns_empty_string_when_header_absent(self, app):
        with app.test_request_context("/"):
            assert _extract_bearer_token() == ""
