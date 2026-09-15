"""Identity extraction from gateway-forwarded requests.

Covers ``app.api.documents._extract_user_id`` directly (which claim wins, which
tokens are refused) and through the HTTP layer, where a rejected identity must
surface as a 401 rather than as an anonymous write.
"""

from __future__ import annotations

import uuid

import jwt
import pytest
from fastapi import Request

from app.api.documents import _extract_user_id, _require_user_id

from .conftest import TEST_JWT_SECRET


def make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw_headers})


def bearer(
    payload: dict, secret: str = TEST_JWT_SECRET, algorithm: str = "HS256"
) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt.encode(payload, secret, algorithm=algorithm)}"}


@pytest.mark.parametrize("algorithm", ["HS256", "HS384"])
def test_extracts_user_id_claim_from_accepted_algorithms(algorithm: str) -> None:
    user_id = uuid.uuid4()

    request = make_request(bearer({"user_id": str(user_id)}, algorithm=algorithm))

    assert _extract_user_id(request) == user_id


def test_extracts_sub_claim_from_auth_service_token() -> None:
    """auth-service mints ``sub``; only legacy tokens carry ``user_id``."""
    user_id = uuid.uuid4()

    claims = {"sub": str(user_id), "email": "otter@otterworks.dev", "type": "access"}

    assert _extract_user_id(make_request(bearer(claims))) == user_id


def test_user_id_claim_wins_over_sub() -> None:
    legacy_id, subject_id = uuid.uuid4(), uuid.uuid4()

    request = make_request(bearer({"user_id": str(legacy_id), "sub": str(subject_id)}))

    assert _extract_user_id(request) == legacy_id


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-authorization-header"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed-token"),
        pytest.param({"Authorization": f"Basic {'x' * 8}"}, id="wrong-scheme"),
    ],
)
def test_rejects_requests_without_a_usable_bearer_token(headers: dict[str, str]) -> None:
    assert _extract_user_id(make_request(headers)) is None


def test_rejects_token_signed_with_another_secret() -> None:
    request = make_request(bearer({"user_id": str(uuid.uuid4())}, secret="someone-elses-secret"))

    assert _extract_user_id(request) is None


def test_rejects_expired_token() -> None:
    request = make_request(bearer({"user_id": str(uuid.uuid4()), "exp": 1_000_000_000}))

    assert _extract_user_id(request) is None


def test_rejects_token_whose_identity_claim_is_not_a_uuid() -> None:
    request = make_request(bearer({"user_id": "otter@otterworks.dev"}))

    assert _extract_user_id(request) is None


def test_rejects_token_without_any_identity_claim() -> None:
    request = make_request(bearer({"email": "otter@otterworks.dev"}))

    assert _extract_user_id(request) is None


def test_gateway_user_id_header_is_ignored_while_a_jwt_secret_is_configured() -> None:
    """With a secret set, only the signed token speaks for the caller."""
    request = make_request({"Authorization": "Bearer not-a-jwt", "X-User-ID": str(uuid.uuid4())})

    assert _extract_user_id(request) is None


def test_falls_back_to_gateway_user_id_header_without_a_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unconfigured secret (local dev): the gateway-injected header is trusted."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    user_id = uuid.uuid4()

    request = make_request({"Authorization": "Bearer anything", "X-User-ID": str(user_id)})

    assert _extract_user_id(request) == user_id


def test_fallback_needs_a_bearer_header_and_a_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)

    assert _extract_user_id(make_request({"X-User-ID": str(uuid.uuid4())})) is None
    bad_uuid = {"Authorization": "Bearer x", "X-User-ID": "nope"}
    assert _extract_user_id(make_request(bad_uuid)) is None


def test_require_user_id_raises_401_when_identity_is_absent() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        _require_user_id(make_request())

    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_create_document_derives_owner_from_the_token(client, owner_id) -> None:
    """The conftest client signs every request as ``owner_id``."""
    response = await client.post("/api/v1/documents", json={"title": "Owned by token"})

    assert response.status_code == 201
    assert response.json()["owner_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_create_document_rejects_an_unsigned_caller(client) -> None:
    response = await client.post(
        "/api/v1/documents",
        json={"title": "Anonymous"},
        headers={"Authorization": "Bearer not-a-jwt"},
    )

    assert response.status_code == 401
