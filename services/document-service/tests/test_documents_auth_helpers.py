"""Unit tests for the auth/chaos helpers in app.api.documents."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

import app.api.documents as documents

SECRET = "document-service-unit-test-secret-key"


def _request(**headers: str) -> Request:
    raw = Headers(headers).raw
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


@pytest.fixture(autouse=True)
def reset_redis_singleton(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(documents, "_redis_client", None)


# ---- _extract_user_id / _require_user_id ----


@pytest.mark.parametrize("algorithm", ["HS256", "HS384"])
def test_extract_user_id_from_signed_token(monkeypatch, algorithm):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    user_id = uuid.uuid4()
    token = jwt.encode({"user_id": str(user_id)}, SECRET, algorithm=algorithm)

    assert documents._extract_user_id(_request(Authorization=f"Bearer {token}")) == user_id


def test_extract_user_id_falls_back_to_sub_claim(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    user_id = uuid.uuid4()
    token = jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")

    assert documents._extract_user_id(_request(Authorization=f"Bearer {token}")) == user_id


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer not-a-jwt"},
    ],
    ids=["missing", "wrong-scheme", "malformed-token"],
)
def test_extract_user_id_returns_none(monkeypatch, headers):
    monkeypatch.setenv("JWT_SECRET", SECRET)

    assert documents._extract_user_id(_request(**headers)) is None


def test_extract_user_id_rejects_token_signed_with_another_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    token = jwt.encode({"user_id": str(uuid.uuid4())}, "some-other-secret", algorithm="HS256")

    assert documents._extract_user_id(_request(Authorization=f"Bearer {token}")) is None


def test_extract_user_id_rejects_non_uuid_subject(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    token = jwt.encode({"user_id": "not-a-uuid"}, SECRET, algorithm="HS256")

    assert documents._extract_user_id(_request(Authorization=f"Bearer {token}")) is None


def test_extract_user_id_ignores_token_without_subject_claim(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    token = jwt.encode({"role": "admin"}, SECRET, algorithm="HS256")

    assert documents._extract_user_id(_request(Authorization=f"Bearer {token}")) is None


def test_extract_user_id_trusts_forwarded_header_when_no_secret_configured(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    user_id = uuid.uuid4()
    request = _request(Authorization="Bearer anything", **{"X-User-ID": str(user_id)})

    assert documents._extract_user_id(request) == user_id


def test_extract_user_id_rejects_malformed_forwarded_header(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    request = _request(Authorization="Bearer anything", **{"X-User-ID": "nope"})

    assert documents._extract_user_id(request) is None


def test_extract_user_id_without_forwarded_header_and_no_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)

    assert documents._extract_user_id(_request(Authorization="Bearer anything")) is None


def test_require_user_id_raises_401_when_unauthenticated(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)

    with pytest.raises(HTTPException) as excinfo:
        documents._require_user_id(_request())

    assert excinfo.value.status_code == 401


# ---- _ensure_owner ----


def test_ensure_owner_accepts_matching_owner():
    user_id = uuid.uuid4()

    documents._ensure_owner(SimpleNamespace(owner_id=user_id), user_id)


@pytest.mark.parametrize("owner", [uuid.uuid4(), None])
def test_ensure_owner_raises_403_for_mismatch(owner):
    with pytest.raises(HTTPException) as excinfo:
        documents._ensure_owner(SimpleNamespace(owner_id=owner), uuid.uuid4())

    assert excinfo.value.status_code == 403


# ---- Redis-backed chaos flags ----


def test_get_redis_builds_a_client_once_from_the_environment(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    factory = MagicMock()
    monkeypatch.setattr(documents.redis_lib, "Redis", factory)

    first = documents._get_redis()
    second = documents._get_redis()

    assert first is second
    factory.assert_called_once()
    assert factory.call_args.kwargs["host"] == "redis.internal"
    assert factory.call_args.kwargs["port"] == 6380


def test_chaos_active_reflects_the_redis_key(monkeypatch):
    redis = MagicMock()
    redis.exists.return_value = 1
    monkeypatch.setattr(documents, "_get_redis", lambda: redis)

    assert documents._chaos_active("chaos:document-service:slow_queries") is True
    redis.exists.assert_called_once_with("chaos:document-service:slow_queries")


def test_chaos_active_is_false_when_redis_is_unreachable(monkeypatch):
    def boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(documents, "_get_redis", boom)

    assert documents._chaos_active("chaos:document-service:slow_queries") is False


async def test_maybe_inject_latency_sleeps_when_the_flag_is_set(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(documents, "_chaos_active", lambda key: True)
    monkeypatch.setattr(documents.asyncio, "sleep", fake_sleep)

    await documents._maybe_inject_latency()

    assert len(slept) == 1
    assert 3.0 <= slept[0] <= 5.0


async def test_maybe_inject_latency_is_a_noop_when_the_flag_is_clear(monkeypatch):
    async def fail_sleep(seconds: float) -> None:
        raise AssertionError("should not sleep")

    monkeypatch.setattr(documents, "_chaos_active", lambda key: False)
    monkeypatch.setattr(documents.asyncio, "sleep", fail_sleep)

    await documents._maybe_inject_latency()
