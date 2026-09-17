"""Tests for the auth / chaos helpers in ``app.api.documents``."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import documents

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


def _bearer(user_id: uuid.UUID, claim: str = "user_id", algorithm: str = "HS256") -> dict[str, str]:
    token = jwt.encode({claim: str(user_id)}, TEST_JWT_SECRET, algorithm=algorithm)
    return {"Authorization": f"Bearer {token}"}


# ---- _get_redis / _chaos_active / _maybe_inject_latency ----


def test_get_redis_builds_client_from_env_and_caches_it(monkeypatch):
    monkeypatch.setattr(documents, "_redis_client", None)
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    factory = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(documents.redis_lib, "Redis", factory)

    first = documents._get_redis()
    second = documents._get_redis()

    assert first is second
    factory.assert_called_once_with(
        host="redis.internal", port=6380, decode_responses=True, socket_timeout=1
    )


def test_chaos_active_reflects_redis_key_presence(monkeypatch):
    redis = MagicMock()
    redis.exists.return_value = 1
    monkeypatch.setattr(documents, "_get_redis", lambda: redis)

    assert documents._chaos_active("chaos:document-service:slow_queries") is True
    redis.exists.assert_called_once_with("chaos:document-service:slow_queries")


def test_chaos_active_is_false_when_redis_is_unreachable(monkeypatch):
    redis = MagicMock()
    redis.exists.side_effect = ConnectionError("redis down")
    monkeypatch.setattr(documents, "_get_redis", lambda: redis)

    assert documents._chaos_active("chaos:document-service:slow_queries") is False


@pytest.mark.asyncio
async def test_maybe_inject_latency_sleeps_when_chaos_flag_is_set(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(documents, "asyncio", SimpleNamespace(sleep=sleep))
    monkeypatch.setattr(documents, "_chaos_active", lambda key: True)

    await documents._maybe_inject_latency()

    delay = sleep.await_args.args[0]
    assert 3.0 <= delay <= 5.0


@pytest.mark.asyncio
async def test_maybe_inject_latency_is_a_noop_without_the_chaos_flag(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(documents, "asyncio", SimpleNamespace(sleep=sleep))
    monkeypatch.setattr(documents, "_chaos_active", lambda key: False)

    await documents._maybe_inject_latency()

    sleep.assert_not_awaited()


# ---- _extract_user_id ----


@pytest.mark.parametrize("claim", ["user_id", "sub"])
def test_extract_user_id_reads_either_claim(claim):
    user_id = uuid.uuid4()
    assert documents._extract_user_id(_request(_bearer(user_id, claim=claim))) == user_id


def test_extract_user_id_accepts_hs384_tokens():
    user_id = uuid.uuid4()
    headers = _bearer(user_id, algorithm="HS384")
    assert documents._extract_user_id(_request(headers)) == user_id


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc123"},
        {"Authorization": "Bearer not-a-jwt"},
    ],
)
def test_extract_user_id_returns_none_for_unusable_authorization(headers):
    assert documents._extract_user_id(_request(headers)) is None


def test_extract_user_id_returns_none_when_token_signature_is_wrong():
    token = jwt.encode({"user_id": str(uuid.uuid4())}, "some-other-secret", algorithm="HS256")
    assert documents._extract_user_id(_request({"Authorization": f"Bearer {token}"})) is None


def test_extract_user_id_returns_none_when_the_claim_is_not_a_uuid():
    token = jwt.encode({"user_id": "not-a-uuid"}, TEST_JWT_SECRET, algorithm="HS256")
    assert documents._extract_user_id(_request({"Authorization": f"Bearer {token}"})) is None


def test_extract_user_id_returns_none_when_the_token_carries_no_identity():
    token = jwt.encode({"email": "a@b.c"}, TEST_JWT_SECRET, algorithm="HS256")
    assert documents._extract_user_id(_request({"Authorization": f"Bearer {token}"})) is None


def test_extract_user_id_falls_back_to_gateway_header_when_no_secret_is_set(monkeypatch):
    monkeypatch.setattr(documents, "_get_jwt_secret", lambda: "")
    user_id = uuid.uuid4()
    headers = {"Authorization": "Bearer opaque", "X-User-ID": str(user_id)}

    assert documents._extract_user_id(_request(headers)) == user_id


@pytest.mark.parametrize("headers", [{}, {"X-User-ID": "not-a-uuid"}])
def test_extract_user_id_rejects_bad_gateway_header_when_no_secret_is_set(monkeypatch, headers):
    monkeypatch.setattr(documents, "_get_jwt_secret", lambda: "")
    headers = {"Authorization": "Bearer opaque", **headers}

    assert documents._extract_user_id(_request(headers)) is None


def test_get_jwt_secret_reads_the_environment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "from-env")
    assert documents._get_jwt_secret() == "from-env"


# ---- _require_user_id / _ensure_owner ----


def test_require_user_id_returns_the_authenticated_user():
    user_id = uuid.uuid4()
    assert documents._require_user_id(_request(_bearer(user_id))) == user_id


def test_require_user_id_raises_401_without_credentials():
    with pytest.raises(HTTPException) as exc:
        documents._require_user_id(_request())

    assert exc.value.status_code == 401
    assert exc.value.detail == "Authentication required"


def test_ensure_owner_allows_the_owner():
    user_id = uuid.uuid4()
    assert documents._ensure_owner(SimpleNamespace(owner_id=user_id), user_id) is None


@pytest.mark.parametrize("document", [SimpleNamespace(owner_id=uuid.uuid4()), object()])
def test_ensure_owner_raises_403_for_everyone_else(document):
    with pytest.raises(HTTPException) as exc:
        documents._ensure_owner(document, uuid.uuid4())

    assert exc.value.status_code == 403
    assert exc.value.detail == "Access denied"
