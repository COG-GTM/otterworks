"""Branch coverage for the request -> user id resolution in app.api.documents."""

import uuid

import jwt
import pytest
from starlette.requests import Request

from app.api.documents import _extract_user_id

SECRET = "extract-user-id-test-secret-pad-32-bytes"  # noqa: S105
USER_ID = uuid.uuid4()


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


def _bearer(payload: dict, key: str = SECRET, algorithm: str = "HS256") -> str:
    return f"Bearer {jwt.encode(payload, key, algorithm=algorithm)}"


@pytest.fixture
def with_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)


@pytest.fixture
def without_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)


@pytest.mark.parametrize(
    "payload",
    [{"user_id": str(USER_ID)}, {"sub": str(USER_ID)}, {"user_id": "", "sub": str(USER_ID)}],
)
def test_jwt_claims_resolve_user(with_secret, payload):
    assert _extract_user_id(_request({"Authorization": _bearer(payload)})) == USER_ID


def test_hs384_token_is_accepted(with_secret):
    token = _bearer({"sub": str(USER_ID)}, algorithm="HS384")
    assert _extract_user_id(_request({"Authorization": token})) == USER_ID


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Basic abc",
        "Bearer not-a-jwt",
        _bearer({"user_id": str(USER_ID)}, key="wrong-secret-wrong-secret-wrong-secret"),
        _bearer({"user_id": str(USER_ID)}, algorithm="HS512"),
        _bearer({"user_id": "not-a-uuid"}),
        _bearer({}),
    ],
)
def test_unusable_authorization_resolves_nobody(with_secret, authorization):
    headers = {"X-User-ID": str(USER_ID)}
    if authorization is not None:
        headers["Authorization"] = authorization
    assert _extract_user_id(_request(headers)) is None


def test_forwarded_header_ignored_when_secret_configured(with_secret):
    headers = {"Authorization": "Bearer opaque", "X-User-ID": str(USER_ID)}
    assert _extract_user_id(_request(headers)) is None


def test_forwarded_header_used_without_secret(without_secret):
    headers = {"Authorization": "Bearer opaque", "X-User-ID": str(USER_ID)}
    assert _extract_user_id(_request(headers)) == USER_ID


@pytest.mark.parametrize("forwarded", [None, "", "not-a-uuid"])
def test_missing_or_bad_forwarded_header_without_secret(without_secret, forwarded):
    headers = {"Authorization": "Bearer opaque"}
    if forwarded is not None:
        headers["X-User-ID"] = forwarded
    assert _extract_user_id(_request(headers)) is None


def test_forwarded_header_requires_bearer_scheme(without_secret):
    assert _extract_user_id(_request({"X-User-ID": str(USER_ID)})) is None
