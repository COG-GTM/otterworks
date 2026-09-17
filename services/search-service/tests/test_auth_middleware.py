"""Tests for the authentication middleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app
from app.middleware.auth import _extract_bearer_token

SERVICE_TOKEN = "s3rvice-t0ken"


def _build_app(mock_client: MagicMock, auth: AuthConfig):
    config = AppConfig(
        service_name="search-service-test",
        meilisearch=MeiliSearchConfig(
            url="http://localhost:7700",
            api_key="",
            documents_index="test-otterworks-documents",
            files_index="test-otterworks-files",
        ),
        sqs=SQSConfig(enabled=False),
        auth=auth,
    )
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_client
        flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def secured_client(mock_meilisearch_client: MagicMock):
    """Client for an app that enforces auth and accepts a service token."""
    app = _build_app(
        mock_meilisearch_client,
        AuthConfig(service_token=SERVICE_TOKEN, require_auth=True),
    )
    return app.test_client()


@pytest.fixture()
def gateway_only_client(mock_meilisearch_client: MagicMock):
    """Client for an app that enforces auth with no service token configured."""
    app = _build_app(mock_meilisearch_client, AuthConfig(service_token="", require_auth=True))
    return app.test_client()


class TestPublicEndpoints:
    """Health and metrics stay reachable without credentials."""

    @pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
    def test_public_paths_bypass_auth(self, secured_client, path):
        """Probe endpoints must never return 401."""
        response = secured_client.get(path)
        assert response.status_code != 401


class TestProtectedEndpoints:
    """Everything else needs a service token or a gateway identity."""

    def test_request_without_credentials_is_rejected(self, secured_client):
        """No token and no X-User-ID means 401."""
        response = secured_client.get("/api/v1/search/?q=test")
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}

    def test_valid_service_token_is_accepted(self, secured_client):
        """A matching bearer token authenticates an internal caller."""
        response = secured_client.get(
            "/api/v1/search/?q=test",
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        )
        assert response.status_code == 200

    def test_wrong_service_token_is_rejected(self, secured_client):
        """A bearer token that does not match the configured one is not enough."""
        response = secured_client.get(
            "/api/v1/search/?q=test", headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401

    def test_gateway_user_header_is_accepted(self, secured_client):
        """The gateway-injected identity authenticates a user request."""
        response = secured_client.get(
            "/api/v1/search/?q=test", headers={"X-User-ID": "user-1"}
        )
        assert response.status_code == 200

    def test_blank_gateway_user_header_is_rejected(self, secured_client):
        """A whitespace-only X-User-ID is not an identity."""
        response = secured_client.get("/api/v1/search/?q=test", headers={"X-User-ID": "   "})
        assert response.status_code == 401

    def test_service_token_is_ignored_when_none_is_configured(self, gateway_only_client):
        """Without a configured token only the gateway path can authenticate."""
        rejected = gateway_only_client.get(
            "/api/v1/search/?q=test", headers={"Authorization": "Bearer anything"}
        )
        assert rejected.status_code == 401

        accepted = gateway_only_client.get(
            "/api/v1/search/?q=test", headers={"X-User-ID": "user-1"}
        )
        assert accepted.status_code == 200

    def test_unknown_path_is_rejected_before_routing(self, secured_client):
        """Auth runs before the 404 handler, so unknown paths are 401 too."""
        response = secured_client.get("/api/v1/search/nope")
        assert response.status_code == 401

    def test_auth_disabled_allows_anonymous_requests(self, client):
        """The default test app disables auth entirely."""
        response = client.get("/api/v1/search/?q=test")
        assert response.status_code == 200


class TestExtractBearerToken:
    """Tests for Authorization header parsing."""

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("Bearer abc123", "abc123"),
            ("bearer abc123", "abc123"),
            ("BEARER  abc123  ", "abc123"),
            ("Basic abc123", ""),
            ("", ""),
            ("Bearer", ""),
        ],
    )
    def test_bearer_token_parsing(self, app, header, expected):
        """Only a bearer scheme yields a token; the value is trimmed."""
        with app.test_request_context("/", headers={"Authorization": header}):
            assert _extract_bearer_token() == expected
