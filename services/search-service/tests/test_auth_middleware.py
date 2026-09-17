"""Authentication modes accepted by the search service.

The service never validates JWTs itself: it trusts the service token given to
internal callers, or the ``X-User-ID`` header the API gateway sets after it has
validated the caller's token.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app

SERVICE_TOKEN = "internal-service-token"  # noqa: S105
GATEWAY_USER_ID = "3f7c1f2e-9d4a-4c3b-8a41-2b6f5e0d1c77"
PROTECTED_PATH = "/api/v1/search?q=otter"


def build_config(*, service_token: str = SERVICE_TOKEN, require_auth: bool = True) -> AppConfig:
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


@pytest.fixture()
def make_client(mock_meilisearch_client: MagicMock):
    def _make(**config_kwargs):
        with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
            mock_cls.return_value = mock_meilisearch_client
            flask_app = create_app(build_config(**config_kwargs))
            flask_app.config["TESTING"] = True
            return flask_app.test_client()

    return _make


@pytest.fixture()
def auth_client(make_client):
    return make_client()


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
def test_health_and_metrics_stay_public(auth_client, path: str) -> None:
    assert auth_client.get(path).status_code != 401


def test_rejects_a_request_with_neither_service_token_nor_gateway_identity(auth_client) -> None:
    response = auth_client.get(PROTECTED_PATH)

    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


def test_accepts_the_configured_service_token(auth_client) -> None:
    response = auth_client.get(PROTECTED_PATH, headers={"Authorization": f"Bearer {SERVICE_TOKEN}"})

    assert response.status_code == 200


def test_bearer_scheme_is_matched_case_insensitively(auth_client) -> None:
    response = auth_client.get(PROTECTED_PATH, headers={"Authorization": f"bearer {SERVICE_TOKEN}"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(f"Bearer {SERVICE_TOKEN}-wrong", id="wrong-token"),
        pytest.param(SERVICE_TOKEN, id="missing-bearer-scheme"),
        pytest.param("Basic aW50ZXJuYWw6dG9rZW4=", id="wrong-scheme"),
        pytest.param("Bearer ", id="empty-token"),
    ],
)
def test_rejects_anything_that_is_not_the_service_token(auth_client, authorization: str) -> None:
    response = auth_client.get(PROTECTED_PATH, headers={"Authorization": authorization})

    assert response.status_code == 401


def test_accepts_gateway_injected_identity(auth_client) -> None:
    response = auth_client.get(PROTECTED_PATH, headers={"X-User-ID": GATEWAY_USER_ID})

    assert response.status_code == 200


def test_gateway_identity_must_be_non_blank(auth_client) -> None:
    assert auth_client.get(PROTECTED_PATH, headers={"X-User-ID": "   "}).status_code == 401
    assert auth_client.get(PROTECTED_PATH, headers={"X-User-ID": ""}).status_code == 401


def test_gateway_identity_is_accepted_without_being_a_uuid(auth_client) -> None:
    """The gateway is trusted: the header's shape is not re-checked here."""
    response = auth_client.get(PROTECTED_PATH, headers={"X-User-ID": "not-a-uuid"})

    assert response.status_code == 200


def test_without_a_service_token_only_the_gateway_path_remains(make_client) -> None:
    client = make_client(service_token="")

    assert client.get(PROTECTED_PATH, headers={"Authorization": "Bearer anything"}).status_code == 401
    assert client.get(PROTECTED_PATH, headers={"X-User-ID": GATEWAY_USER_ID}).status_code == 200


def test_auth_can_be_disabled_entirely(make_client) -> None:
    client = make_client(require_auth=False)

    assert client.get(PROTECTED_PATH).status_code == 200
