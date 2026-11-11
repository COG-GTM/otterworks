"""Tests for the search service authentication middleware."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app

JWT_SECRET = "test-jwt-secret-with-enough-length-for-hs256"
SERVICE_TOKEN = "test-service-token"
ALICE = "11111111-1111-1111-1111-111111111111"
MALLORY = "22222222-2222-2222-2222-222222222222"


def _make_token(sub: str, secret: str = JWT_SECRET, **claims) -> str:
    payload = {"sub": sub, "type": "access", "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, secret, algorithm="HS256")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _build_client(mock_meilisearch_client: MagicMock, auth: AuthConfig):
    config = AppConfig(
        meilisearch=MeiliSearchConfig(url="http://localhost:7700", api_key=""),
        sqs=SQSConfig(enabled=False),
        auth=auth,
    )
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture()
def secure_client(mock_meilisearch_client):
    return _build_client(
        mock_meilisearch_client,
        AuthConfig(service_token=SERVICE_TOKEN, jwt_secret=JWT_SECRET, require_auth=True),
    )


def _search_filter(mock_meilisearch_client: MagicMock) -> str:
    mock_index = mock_meilisearch_client.index.return_value
    return mock_index.search.call_args.args[1].get("filter", "")


class TestUserRoutes:
    def test_health_is_public(self, secure_client):
        assert secure_client.get("/health").status_code == 200

    def test_forged_user_header_without_token_rejected(self, secure_client):
        response = secure_client.post(
            "/api/v1/search/advanced", json={}, headers={"X-User-ID": ALICE}
        )
        assert response.status_code == 401

    def test_token_signed_with_wrong_secret_rejected(self, secure_client):
        token = _make_token(ALICE, secret="not-the-real-secret-but-long-enough-to-sign")
        response = secure_client.get("/api/v1/search/?q=x", headers=_bearer(token))
        assert response.status_code == 401

    def test_expired_token_rejected(self, secure_client):
        token = _make_token(ALICE, exp=int(time.time()) - 10)
        response = secure_client.get("/api/v1/search/?q=x", headers=_bearer(token))
        assert response.status_code == 401

    def test_token_without_exp_rejected(self, secure_client):
        token = jwt.encode({"sub": ALICE}, JWT_SECRET, algorithm="HS256")
        response = secure_client.get("/api/v1/search/?q=x", headers=_bearer(token))
        assert response.status_code == 401

    def test_refresh_token_rejected(self, secure_client):
        token = _make_token(ALICE, type="refresh")
        response = secure_client.get("/api/v1/search/?q=x", headers=_bearer(token))
        assert response.status_code == 401

    def test_mismatched_user_header_rejected(self, secure_client):
        headers = {**_bearer(_make_token(MALLORY)), "X-User-ID": ALICE}
        response = secure_client.post("/api/v1/search/advanced", json={}, headers=headers)
        assert response.status_code == 401

    def test_search_scoped_to_token_subject(self, secure_client, mock_meilisearch_client):
        headers = {**_bearer(_make_token(ALICE)), "X-User-ID": ALICE}
        response = secure_client.get("/api/v1/search/?q=design", headers=headers)
        assert response.status_code == 200
        assert f'owner_id = "{ALICE}"' in _search_filter(mock_meilisearch_client)

    def test_advanced_search_scoped_to_token_subject(self, secure_client, mock_meilisearch_client):
        response = secure_client.post(
            "/api/v1/search/advanced", json={}, headers=_bearer(_make_token(ALICE))
        )
        assert response.status_code == 200
        assert f'owner_id = "{ALICE}"' in _search_filter(mock_meilisearch_client)

    def test_user_id_claim_fallback(self, secure_client, mock_meilisearch_client):
        token = jwt.encode(
            {"user_id": ALICE, "exp": int(time.time()) + 300}, JWT_SECRET, algorithm="HS256"
        )
        response = secure_client.get("/api/v1/search/?q=design", headers=_bearer(token))
        assert response.status_code == 200
        assert f'owner_id = "{ALICE}"' in _search_filter(mock_meilisearch_client)

    def test_missing_jwt_secret_fails_closed(self, mock_meilisearch_client):
        client = _build_client(
            mock_meilisearch_client,
            AuthConfig(service_token="", jwt_secret="", require_auth=True),
        )
        response = client.get("/api/v1/search/?q=x", headers=_bearer(_make_token(ALICE)))
        assert response.status_code == 401

    def test_service_token_accepted_on_user_routes(self, secure_client):
        response = secure_client.get("/api/v1/search/suggest?q=te", headers=_bearer(SERVICE_TOKEN))
        assert response.status_code == 200


INDEX_REQUESTS = [
    ("post", "/api/v1/search/index/document", {"id": "doc-1", "title": "T", "owner_id": ALICE}),
    ("post", "/api/v1/search/index/file", {"id": "file-1", "name": "f.pdf", "owner_id": ALICE}),
    ("delete", "/api/v1/search/index/document/doc-1", None),
    ("post", "/api/v1/search/reindex", None),
]


class TestInternalRoutes:
    @pytest.mark.parametrize(("method", "path", "body"), INDEX_REQUESTS)
    def test_user_jwt_cannot_write_index(self, secure_client, method, path, body):
        headers = {**_bearer(_make_token(MALLORY)), "X-User-ID": MALLORY}
        response = getattr(secure_client, method)(path, json=body, headers=headers)
        assert response.status_code == 401

    @pytest.mark.parametrize(("method", "path", "body"), INDEX_REQUESTS)
    def test_wrong_service_token_rejected(self, secure_client, method, path, body):
        response = getattr(secure_client, method)(path, json=body, headers=_bearer("guess"))
        assert response.status_code == 401

    @pytest.mark.parametrize(("method", "path", "body"), INDEX_REQUESTS)
    def test_service_token_allowed(self, secure_client, method, path, body):
        response = getattr(secure_client, method)(path, json=body, headers=_bearer(SERVICE_TOKEN))
        assert response.status_code in (200, 201)

    @pytest.mark.parametrize(("method", "path", "body"), INDEX_REQUESTS)
    def test_internal_routes_closed_even_when_auth_disabled(
        self, mock_meilisearch_client, method, path, body
    ):
        client = _build_client(
            mock_meilisearch_client,
            AuthConfig(service_token="", jwt_secret="", require_auth=False),
        )
        response = getattr(client, method)(path, json=body, headers={"X-User-ID": MALLORY})
        assert response.status_code == 401
