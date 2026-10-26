"""Authentication tests: identity comes from a verified JWT, never from X-User-ID."""

from __future__ import annotations

import time

import jwt
import pytest

from tests.conftest import (
    TEST_JWT_SECRET,
    TEST_SERVICE_TOKEN,
    TEST_USER_ID,
    bearer,
    make_token,
)

SEARCH_ROUTES = [
    ("get", "/api/v1/search/?q=design", None),
    ("post", "/api/v1/search/advanced", {}),
]


def _call(test_client, method, path, body, headers):
    if method == "post":
        return test_client.post(path, json=body, headers=headers)
    return test_client.get(path, headers=headers)


def _owner_filters(mock_meilisearch_client) -> list[str]:
    index = mock_meilisearch_client.index.return_value
    return [c.args[1].get("filter", "") for c in index.search.call_args_list]


class TestForgedIdentityHeader:
    @pytest.mark.parametrize(("method", "path", "body"), SEARCH_ROUTES)
    def test_forged_x_user_id_without_token_is_rejected(
        self, anon_client, mock_meilisearch_client, method, path, body
    ):
        resp = _call(anon_client, method, path, body, {"X-User-ID": "user-victim"})
        assert resp.status_code == 401
        assert mock_meilisearch_client.index.return_value.search.call_count == 0

    @pytest.mark.parametrize(("method", "path", "body"), SEARCH_ROUTES)
    def test_results_are_scoped_to_token_subject_not_header(
        self, anon_client, mock_meilisearch_client, method, path, body
    ):
        headers = {**bearer(make_token("user-mallory")), "X-User-ID": "user-victim"}
        resp = _call(anon_client, method, path, body, headers)
        assert resp.status_code == 200
        filters = _owner_filters(mock_meilisearch_client)
        assert filters
        assert all('owner_id = "user-mallory"' in f for f in filters)
        assert not any("user-victim" in f for f in filters)

    def test_user_id_claim_is_used_when_sub_is_absent(self, anon_client, mock_meilisearch_client):
        resp = anon_client.get(
            "/api/v1/search/?q=x", headers=bearer(make_token(sub=None, user_id="user-bob"))
        )
        assert resp.status_code == 200
        assert all('owner_id = "user-bob"' in f for f in _owner_filters(mock_meilisearch_client))


class TestTokenValidation:
    def _expect_401(self, anon_client, token):
        resp = anon_client.post("/api/v1/search/advanced", json={}, headers=bearer(token))
        assert resp.status_code == 401
        assert resp.get_json() == {"error": "unauthorized"}

    def test_missing_token(self, anon_client):
        assert anon_client.post("/api/v1/search/advanced", json={}).status_code == 401

    def test_wrong_signing_key(self, anon_client):
        self._expect_401(anon_client, make_token(secret="not-the-shared-secret-at-all-000000"))

    def test_expired_token(self, anon_client):
        self._expect_401(anon_client, make_token(exp=int(time.time()) - 60))

    def test_token_without_exp(self, anon_client):
        token = jwt.encode({"sub": TEST_USER_ID, "type": "access"}, TEST_JWT_SECRET, algorithm="HS256")
        self._expect_401(anon_client, token)

    def test_refresh_token(self, anon_client):
        self._expect_401(anon_client, make_token(type="refresh"))

    def test_token_without_subject(self, anon_client):
        self._expect_401(anon_client, make_token(sub=None))

    def test_alg_none(self, anon_client):
        token = jwt.encode(
            {"sub": TEST_USER_ID, "exp": int(time.time()) + 300}, key=None, algorithm="none"
        )
        self._expect_401(anon_client, token)

    def test_hs512_token_from_auth_service_is_accepted(self, anon_client):
        token = jwt.encode(
            {"sub": TEST_USER_ID, "type": "access", "exp": int(time.time()) + 300},
            TEST_JWT_SECRET,
            algorithm="HS512",
        )
        resp = anon_client.get("/api/v1/search/?q=x", headers=bearer(token))
        assert resp.status_code == 200

    def test_basic_auth_scheme_is_not_a_token(self, anon_client):
        resp = anon_client.get("/api/v1/search/?q=x", headers={"Authorization": "Basic Zm9vOmJhcg=="})
        assert resp.status_code == 401


class TestServiceToken:
    def test_service_token_can_index(self, anon_client):
        resp = anon_client.post(
            "/api/v1/search/index/document",
            json={"id": "doc-1", "title": "T", "owner_id": "user-1"},
            headers=bearer(TEST_SERVICE_TOKEN),
        )
        assert resp.status_code in (200, 201)

    @pytest.mark.parametrize(("method", "path", "body"), SEARCH_ROUTES)
    def test_service_token_cannot_run_unscoped_user_search(
        self, anon_client, mock_meilisearch_client, method, path, body
    ):
        headers = {**bearer(TEST_SERVICE_TOKEN), "X-User-ID": "user-victim"}
        resp = _call(anon_client, method, path, body, headers)
        assert resp.status_code == 403
        assert mock_meilisearch_client.index.return_value.search.call_count == 0

    def test_near_miss_service_token_is_rejected(self, anon_client):
        resp = anon_client.post(
            "/api/v1/search/index/document",
            json={"id": "doc-1", "title": "T", "owner_id": "user-1"},
            headers=bearer(TEST_SERVICE_TOKEN + "x"),
        )
        assert resp.status_code == 401


class TestPublicAndUnconfigured:
    def test_health_and_metrics_need_no_token(self, anon_client):
        assert anon_client.get("/health").status_code == 200
        assert anon_client.get("/metrics").status_code == 200

    def test_without_jwt_secret_user_tokens_fail_closed(self, app_config, mock_meilisearch_client):
        from dataclasses import replace
        from unittest.mock import patch

        from app.config import AuthConfig
        from app.main import create_app

        config = replace(app_config, auth=AuthConfig(service_token="", jwt_secret=""))
        with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
            mock_cls.return_value = mock_meilisearch_client
            app = create_app(config)
        test_client = app.test_client()
        resp = test_client.get(
            "/api/v1/search/?q=x", headers={**bearer(make_token()), "X-User-ID": TEST_USER_ID}
        )
        assert resp.status_code == 401

    def test_require_auth_env_no_longer_disables_auth(self, monkeypatch):
        from app.config import AuthConfig

        monkeypatch.setenv("REQUIRE_AUTH", "false")
        assert not hasattr(AuthConfig(), "require_auth")
