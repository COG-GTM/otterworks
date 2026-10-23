"""Authentication and tenant-scoping tests with auth enabled."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
import meilisearch
import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app

JWT_SECRET = "test-jwt-secret-that-is-long-enough-for-hs512-signing-0123456789abcdef"
SERVICE_TOKEN = "test-service-token"
VICTIM = "11111111-1111-1111-1111-111111111111"
ATTACKER = "22222222-2222-2222-2222-222222222222"


def _token(sub: str = ATTACKER, secret: str = JWT_SECRET, algorithm: str = "HS512", **claims) -> str:
    payload = {"sub": sub, "type": "access", "exp": int(time.time()) + 300, **claims}
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, secret, algorithm=algorithm)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _build_client(mock_meilisearch_client: MagicMock, jwt_secret: str = JWT_SECRET):
    config = AppConfig(
        service_name="search-service-test",
        meilisearch=MeiliSearchConfig(url="http://localhost:7700", api_key=""),
        sqs=SQSConfig(enabled=False),
        auth=AuthConfig(service_token=SERVICE_TOKEN, require_auth=True, jwt_secret=jwt_secret),
    )
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture()
def auth_client(mock_meilisearch_client):
    return _build_client(mock_meilisearch_client)


@pytest.fixture()
def mock_index(mock_meilisearch_client):
    return mock_meilisearch_client.index.return_value


def _search_filters(mock_index: MagicMock) -> list[str]:
    return [c.args[1].get("filter", "") for c in mock_index.search.call_args_list]


class TestForgedIdentity:
    """A client that reaches the service directly cannot pick its identity."""

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("get", "/api/v1/search/?q=secret", None),
            ("post", "/api/v1/search/advanced", {"q": "secret"}),
            ("get", "/api/v1/search/suggest?q=se", None),
            ("get", "/api/v1/search/analytics", None),
            ("post", "/api/v1/search/index/document", {"id": "d1", "title": "t", "owner_id": VICTIM}),
            ("post", "/api/v1/search/index/file", {"id": "f1", "name": "n", "owner_id": VICTIM}),
            ("delete", "/api/v1/search/index/document/d1", None),
            ("post", "/api/v1/search/reindex", None),
        ],
    )
    def test_x_user_id_without_token_is_rejected(self, auth_client, mock_index, method, path, body):
        response = getattr(auth_client, method)(path, headers={"X-User-ID": VICTIM}, json=body)
        assert response.status_code == 401
        mock_index.search.assert_not_called()
        mock_index.add_documents.assert_not_called()
        mock_index.delete_document.assert_not_called()

    @pytest.mark.parametrize(
        "token",
        [
            _token(sub=VICTIM, secret="wrong-secret-" * 6),
            _token(sub=VICTIM, exp=int(time.time()) - 10),
            _token(sub=VICTIM, exp=None),
            _token(sub=VICTIM, type="refresh"),
            _token(sub=None),
            jwt.encode({"sub": VICTIM, "exp": int(time.time()) + 300}, key=None, algorithm="none"),
            "not-a-jwt",
        ],
        ids=["bad-signature", "expired", "no-exp", "refresh-token", "no-subject", "alg-none", "garbage"],
    )
    def test_unverifiable_tokens_are_rejected(self, auth_client, mock_index, token):
        response = auth_client.get("/api/v1/search/?q=secret", headers=_bearer(token))
        assert response.status_code == 401
        mock_index.search.assert_not_called()

    def test_missing_jwt_secret_fails_closed(self, mock_meilisearch_client):
        client = _build_client(mock_meilisearch_client, jwt_secret="")
        response = client.get("/api/v1/search/?q=secret", headers=_bearer(_token()))
        assert response.status_code == 401

    def test_health_stays_public(self, auth_client):
        assert auth_client.get("/health").status_code == 200


class TestVerifiedIdentityScopesResults:
    def test_search_is_scoped_to_the_token_subject_not_the_header(self, auth_client, mock_index):
        response = auth_client.get(
            "/api/v1/search/?q=secret",
            headers={**_bearer(_token(sub=ATTACKER)), "X-User-ID": VICTIM},
        )
        assert response.status_code == 200
        filters = _search_filters(mock_index)
        assert filters and all(f'owner_id = "{ATTACKER}"' in f for f in filters)
        assert not any(VICTIM in f for f in filters)

    def test_user_id_claim_is_accepted_when_sub_is_absent(self, auth_client, mock_index):
        token = _token(sub=None, user_id=ATTACKER, algorithm="HS256")
        response = auth_client.get("/api/v1/search/?q=secret", headers=_bearer(token))
        assert response.status_code == 200
        assert all(f'owner_id = "{ATTACKER}"' in f for f in _search_filters(mock_index))

    def test_advanced_search_is_scoped_to_the_token_subject(self, auth_client, mock_index):
        response = auth_client.post(
            "/api/v1/search/advanced",
            headers={**_bearer(_token(sub=ATTACKER)), "X-User-ID": VICTIM},
            json={"q": "secret", "owner_id": VICTIM},
        )
        assert response.status_code == 200
        filters = _search_filters(mock_index)
        assert filters and all(f'owner_id = "{ATTACKER}"' in f for f in filters)

    def test_suggest_is_scoped_to_the_token_subject(self, auth_client, mock_index):
        response = auth_client.get("/api/v1/search/suggest?q=se", headers=_bearer(_token(sub=ATTACKER)))
        assert response.status_code == 200
        filters = _search_filters(mock_index)
        assert filters and all(f == f'owner_id = "{ATTACKER}"' for f in filters)


class TestServiceToken:
    def test_service_token_cannot_run_unscoped_searches(self, auth_client, mock_index):
        for method, path, body in [
            ("get", "/api/v1/search/?q=secret", None),
            ("post", "/api/v1/search/advanced", {"q": "secret"}),
            ("get", "/api/v1/search/suggest?q=se", None),
        ]:
            response = getattr(auth_client, method)(path, headers=_bearer(SERVICE_TOKEN), json=body)
            assert response.status_code == 403, path
        mock_index.search.assert_not_called()

    def test_service_token_can_index_for_any_owner(self, auth_client, mock_index):
        response = auth_client.post(
            "/api/v1/search/index/document",
            headers=_bearer(SERVICE_TOKEN),
            json={"id": "d1", "title": "t", "owner_id": VICTIM},
        )
        assert response.status_code == 201
        assert mock_index.add_documents.call_args.args[0][0]["owner_id"] == VICTIM

    def test_analytics_requires_the_service_token(self, auth_client, mock_meilisearch_client):
        mock_meilisearch_client.get_indexes.return_value = {"results": []}
        assert auth_client.get("/api/v1/search/analytics", headers=_bearer(_token())).status_code == 403
        assert auth_client.get("/api/v1/search/analytics", headers=_bearer(SERVICE_TOKEN)).status_code == 200

    def test_reindex_requires_the_service_token(self, auth_client):
        with patch("app.api.index.Indexer.reindex", return_value={"status": "reindexed"}) as reindex:
            assert auth_client.post("/api/v1/search/reindex", headers=_bearer(_token())).status_code == 403
            reindex.assert_not_called()
            response = auth_client.post("/api/v1/search/reindex", headers=_bearer(SERVICE_TOKEN))
            assert response.status_code == 200
            reindex.assert_called_once()

    def test_a_token_that_merely_starts_like_the_service_token_is_rejected(self, auth_client):
        response = auth_client.post("/api/v1/search/reindex", headers=_bearer(SERVICE_TOKEN + "x"))
        assert response.status_code == 401


class TestUserIndexOwnership:
    def _not_indexed(self, mock_index):
        response = SimpleNamespace(
            status_code=404,
            text='{"message": "not found", "code": "document_not_found", "type": "invalid_request", "link": ""}',
        )
        mock_index.get_document.side_effect = meilisearch.errors.MeilisearchApiError("not found", response)

    def test_user_cannot_index_on_behalf_of_another_owner(self, auth_client, mock_index):
        self._not_indexed(mock_index)
        response = auth_client.post(
            "/api/v1/search/index/document",
            headers=_bearer(_token(sub=ATTACKER)),
            json={"id": "d1", "title": "planted", "owner_id": VICTIM},
        )
        assert response.status_code == 403
        mock_index.add_documents.assert_not_called()

    def test_owner_defaults_to_the_caller(self, auth_client, mock_index):
        self._not_indexed(mock_index)
        response = auth_client.post(
            "/api/v1/search/index/file",
            headers=_bearer(_token(sub=ATTACKER)),
            json={"id": "f1", "name": "mine.txt"},
        )
        assert response.status_code == 201
        assert mock_index.add_documents.call_args.args[0][0]["owner_id"] == ATTACKER

    def test_user_can_index_their_own_entry(self, auth_client, mock_index):
        mock_index.get_document.return_value = {"id": "d1", "owner_id": ATTACKER}
        response = auth_client.post(
            "/api/v1/search/index/document",
            headers=_bearer(_token(sub=ATTACKER)),
            json={"id": "d1", "title": "mine", "owner_id": ATTACKER},
        )
        assert response.status_code == 201

    def test_user_cannot_overwrite_another_users_entry(self, auth_client, mock_index):
        mock_index.get_document.return_value = {"id": "d1", "owner_id": VICTIM}
        response = auth_client.post(
            "/api/v1/search/index/document",
            headers=_bearer(_token(sub=ATTACKER)),
            json={"id": "d1", "title": "hijacked"},
        )
        assert response.status_code == 403
        mock_index.add_documents.assert_not_called()

    def test_user_cannot_delete_another_users_entry(self, auth_client, mock_index):
        mock_index.get_document.return_value = {"id": "d1", "owner_id": VICTIM}
        response = auth_client.delete(
            "/api/v1/search/index/document/d1", headers=_bearer(_token(sub=ATTACKER))
        )
        assert response.status_code == 404
        mock_index.delete_document.assert_not_called()

    def test_user_can_delete_their_own_entry(self, auth_client, mock_index):
        mock_index.get_document.return_value = {"id": "d1", "owner_id": ATTACKER}
        response = auth_client.delete(
            "/api/v1/search/index/document/d1", headers=_bearer(_token(sub=ATTACKER))
        )
        assert response.status_code == 200
        mock_index.delete_document.assert_called_once_with("d1")
