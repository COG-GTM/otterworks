"""Pytest fixtures for Search Service tests."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app
from app.services.meilisearch_client import MeiliSearchService

TEST_JWT_SECRET = "search-service-test-jwt-secret-" + "0123456789abcdef" * 3
TEST_SERVICE_TOKEN = "search-service-test-service-token"
TEST_USER_ID = "user-alice"


def make_token(sub: str | None = TEST_USER_ID, secret: str = TEST_JWT_SECRET, **claims) -> str:
    """Sign an access token the way auth-service does."""
    now = int(time.time())
    payload = {"type": "access", "iat": now, "exp": now + 300, **claims}
    if sub is not None:
        payload["sub"] = sub
    return jwt.encode(payload, secret, algorithm="HS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def app_config() -> AppConfig:
    """Create a test AppConfig with a known JWT secret and service token."""
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
        auth=AuthConfig(service_token=TEST_SERVICE_TOKEN, jwt_secret=TEST_JWT_SECRET),
    )


@pytest.fixture()
def mock_meilisearch_client() -> MagicMock:
    """Create a mock meilisearch.Client."""
    mock = MagicMock()

    mock_health = {"status": "available"}
    mock.health.return_value = mock_health

    mock_task = MagicMock()
    mock_task.task_uid = 1
    mock_task_result = MagicMock()
    mock_task_result.status = "succeeded"
    mock.wait_for_task.return_value = mock_task_result

    mock_index = MagicMock()
    mock_index.add_documents.return_value = mock_task
    mock_index.delete_document.return_value = mock_task
    mock_index.search.return_value = {"hits": [], "estimatedTotalHits": 0}
    mock.index.return_value = mock_index

    mock.create_index.return_value = mock_task
    mock.delete_index.return_value = mock_task
    mock.get_index.side_effect = None

    return mock


@pytest.fixture()
def app(app_config: AppConfig, mock_meilisearch_client: MagicMock):
    """Create a Flask test app with mocked MeiliSearch."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        flask_app = create_app(app_config)
        flask_app.config["TESTING"] = True
        yield flask_app


@pytest.fixture()
def client(app):
    """A Flask test client authenticated as ``TEST_USER_ID`` with a valid access token."""
    test_client = app.test_client()
    test_client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {make_token()}"
    return test_client


@pytest.fixture()
def service_client(app):
    """A Flask test client authenticated with the service-to-service token."""
    test_client = app.test_client()
    test_client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {TEST_SERVICE_TOKEN}"
    return test_client


@pytest.fixture()
def anon_client(app):
    """A Flask test client that sends no credentials unless a test adds them."""
    return app.test_client()


@pytest.fixture()
def meilisearch_service(app_config: AppConfig, mock_meilisearch_client: MagicMock) -> MeiliSearchService:
    """Create a MeiliSearchService with a mocked client."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        service = MeiliSearchService(app_config.meilisearch)
        return service
