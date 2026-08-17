"""Tests for the auth/chaos helpers in app.api.documents."""

import asyncio
import uuid

import jwt
import pytest
from fastapi import HTTPException
from httpx import Headers

import app.api.documents as documents_mod
from app.api.documents import (
    _chaos_active,
    _ensure_owner,
    _extract_user_id,
    _get_jwt_secret,
    _get_redis,
    _maybe_inject_latency,
    _require_user_id,
)

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105


class _FakeRequest:
    """Minimal stand-in for starlette's Request: helpers only read headers."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = Headers(headers or {})


def _bearer(payload: dict[str, str], secret: str = TEST_JWT_SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt.encode(payload, secret, algorithm='HS256')}"}


def test_get_redis_is_lazy_and_cached(monkeypatch):
    monkeypatch.setattr(documents_mod, "_redis_client", None)
    monkeypatch.setenv("REDIS_HOST", "redis.test")
    monkeypatch.setenv("REDIS_PORT", "6380")
    created = []

    class _FakeRedis:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(documents_mod.redis_lib, "Redis", _FakeRedis)

    first = _get_redis()
    second = _get_redis()

    assert first is second
    assert len(created) == 1
    assert created[0]["host"] == "redis.test"
    assert created[0]["port"] == 6380


def test_chaos_active_reflects_redis_key(monkeypatch):
    class _FakeRedis:
        def exists(self, key):
            return 1 if key == "chaos:on" else 0

    monkeypatch.setattr(documents_mod, "_get_redis", lambda: _FakeRedis())

    assert _chaos_active("chaos:on") is True
    assert _chaos_active("chaos:off") is False


def test_chaos_active_is_false_when_redis_unavailable(monkeypatch):
    def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(documents_mod, "_get_redis", _boom)

    assert _chaos_active("chaos:anything") is False


@pytest.mark.asyncio
async def test_maybe_inject_latency_sleeps_when_flag_set(monkeypatch):
    monkeypatch.setattr(documents_mod, "_chaos_active", lambda key: True)
    slept: list[float] = []

    async def _fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    await _maybe_inject_latency()

    assert len(slept) == 1
    assert 3.0 <= slept[0] <= 5.0


@pytest.mark.asyncio
async def test_maybe_inject_latency_is_noop_without_flag(monkeypatch):
    monkeypatch.setattr(documents_mod, "_chaos_active", lambda key: False)

    async def _fail_sleep(seconds):
        raise AssertionError("latency must not be injected")

    monkeypatch.setattr(asyncio, "sleep", _fail_sleep)

    await _maybe_inject_latency()


def test_get_jwt_secret_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    assert _get_jwt_secret() == ""

    monkeypatch.setenv("JWT_SECRET", "s3cret")
    assert _get_jwt_secret() == "s3cret"


def test_extract_user_id_from_user_id_claim(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    user_id = uuid.uuid4()

    assert _extract_user_id(_FakeRequest(_bearer({"user_id": str(user_id)}))) == user_id


def test_extract_user_id_falls_back_to_sub_claim(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    user_id = uuid.uuid4()

    assert _extract_user_id(_FakeRequest(_bearer({"sub": str(user_id)}))) == user_id


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc123"},
        {"Authorization": "Bearer "},
    ],
)
def test_extract_user_id_without_bearer_token_returns_none(monkeypatch, headers):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)

    assert _extract_user_id(_FakeRequest(headers)) is None


def test_extract_user_id_rejects_token_signed_with_another_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    headers = _bearer({"user_id": str(uuid.uuid4())}, secret="a-different-secret")

    assert _extract_user_id(_FakeRequest(headers)) is None


def test_extract_user_id_rejects_non_uuid_claim(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)

    assert _extract_user_id(_FakeRequest(_bearer({"user_id": "not-a-uuid"}))) is None


def test_extract_user_id_returns_none_when_token_has_no_identity(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)

    assert _extract_user_id(_FakeRequest(_bearer({"role": "admin"}))) is None


def test_extract_user_id_uses_forwarded_header_when_no_secret_configured(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "")
    user_id = uuid.uuid4()
    request = _FakeRequest({"Authorization": "Bearer whatever", "X-User-ID": str(user_id)})

    assert _extract_user_id(request) == user_id


@pytest.mark.parametrize("forwarded", ["not-a-uuid", None])
def test_extract_user_id_forwarded_header_invalid_or_absent(monkeypatch, forwarded):
    monkeypatch.setenv("JWT_SECRET", "")
    headers = {"Authorization": "Bearer whatever"}
    if forwarded is not None:
        headers["X-User-ID"] = forwarded

    assert _extract_user_id(_FakeRequest(headers)) is None


def test_require_user_id_raises_401_when_unauthenticated(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)

    with pytest.raises(HTTPException) as exc:
        _require_user_id(_FakeRequest())

    assert exc.value.status_code == 401
    assert exc.value.detail == "Authentication required"


def test_require_user_id_returns_authenticated_id(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    user_id = uuid.uuid4()

    assert _require_user_id(_FakeRequest(_bearer({"user_id": str(user_id)}))) == user_id


def test_ensure_owner_allows_owner_and_rejects_others():
    class _Doc:
        def __init__(self, owner_id):
            self.owner_id = owner_id

    user_id = uuid.uuid4()
    _ensure_owner(_Doc(user_id), user_id)

    with pytest.raises(HTTPException) as exc:
        _ensure_owner(_Doc(uuid.uuid4()), user_id)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Access denied"


def test_ensure_owner_rejects_object_without_owner():
    with pytest.raises(HTTPException) as exc:
        _ensure_owner(object(), uuid.uuid4())

    assert exc.value.status_code == 403
