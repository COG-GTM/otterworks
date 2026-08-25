"""Tests for the search-service authentication middleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app
from app.middleware.auth import _extract_bearer_token


def _build_app(mock_client: MagicMock, *, require_auth: bool, service_token: str) -> Flask:
    config = AppConfig(
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
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_client
        flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def secured_client(mock_meilisearch_client: MagicMock):
    """A test client for an app with auth enforced and a service token set."""
    app = _build_app(mock_meilisearch_client, require_auth=True, service_token="s3cret")
    return app.test_client()


@pytest.fixture()
def gateway_only_client(mock_meilisearch_client: MagicMock):
    """A test client for an app with auth enforced but no service token."""
    app = _build_app(mock_meilisearch_client, require_auth=True, service_token="")
    return app.test_client()


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
def test_public_paths_are_exempt_from_auth(secured_client, path):
    """Health and metrics endpoints stay reachable without credentials."""
    response = secured_client.get(path)
    assert response.status_code != 401


def test_request_without_credentials_is_rejected(secured_client):
    """A protected endpoint returns 401 when no identity is presented."""
    response = secured_client.get("/api/v1/search/?q=test")
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


def test_valid_service_token_is_accepted(secured_client):
    """A matching bearer service token authenticates internal callers."""
    response = secured_client.get(
        "/api/v1/search/?q=test", headers={"Authorization": "Bearer s3cret"}
    )
    assert response.status_code == 200


def test_bearer_scheme_is_matched_case_insensitively(secured_client):
    """The Authorization scheme comparison ignores case."""
    response = secured_client.get(
        "/api/v1/search/?q=test", headers={"Authorization": "bearer s3cret"}
    )
    assert response.status_code == 200


def test_wrong_service_token_falls_through_to_rejection(secured_client):
    """A bearer token that does not match the configured one is not enough."""
    response = secured_client.get(
        "/api/v1/search/?q=test", headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 401


def test_gateway_injected_user_id_is_accepted(secured_client):
    """X-User-ID from the API gateway authenticates user-facing requests."""
    response = secured_client.get("/api/v1/search/?q=test", headers={"X-User-ID": "user-1"})
    assert response.status_code == 200


def test_blank_user_id_header_is_rejected(secured_client):
    """A whitespace-only X-User-ID is treated as no identity at all."""
    response = secured_client.get("/api/v1/search/?q=test", headers={"X-User-ID": "   "})
    assert response.status_code == 401


def test_gateway_identity_is_the_only_path_without_a_service_token(gateway_only_client):
    """With no service token configured, only the gateway header authenticates."""
    assert gateway_only_client.get(
        "/api/v1/search/?q=test", headers={"Authorization": "Bearer anything"}
    ).status_code == 401
    assert gateway_only_client.get(
        "/api/v1/search/?q=test", headers={"X-User-ID": "user-1"}
    ).status_code == 200


def test_auth_disabled_allows_anonymous_requests(client):
    """When require_auth is false every endpoint is open (local dev)."""
    assert client.get("/api/v1/search/?q=test").status_code == 200


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer  abc  ", "abc"),
        ("Basic abc", ""),
        ("", ""),
    ],
)
def test_extract_bearer_token(app, header, expected):
    """The bearer extractor only accepts the Bearer scheme and trims the token."""
    with app.test_request_context("/", headers={"Authorization": header}):
        assert _extract_bearer_token() == expected
