from __future__ import annotations

import time

import jwt
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.security import MANAGE_RATES, Principal, decode_token, require

SECRET = "unit-test-secret-" + "x" * 64


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"database_url": "postgresql://unused", "JWT_SECRET": SECRET}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def token(secret: str = SECRET, alg: str = "HS256", **claims: object) -> str:
    payload: dict[str, object] = {
        "sub": "user-1",
        "roles": ["USER"],
        "tenant_id": "northwind-mutual",
        "type": "access",
        "exp": int(time.time()) + 300,
    }
    payload.update(claims)
    return jwt.encode({k: v for k, v in payload.items() if v is not None}, secret, algorithm=alg)


@pytest.mark.parametrize("alg", ["HS256", "HS384", "HS512"])
def test_auth_service_style_token_accepted(alg: str) -> None:
    principal = decode_token(token(alg=alg, roles=["ADMIN"]), settings())
    assert principal == Principal("user-1", "northwind-mutual", frozenset({"ADMIN"}))


def test_user_id_claim_fallback_and_role_prefix() -> None:
    principal = decode_token(token(sub=None, user_id="u-9", roles=["ROLE_owner"]), settings())
    assert (principal.subject, principal.roles) == ("u-9", frozenset({"OWNER"}))


@pytest.mark.parametrize(
    "bad",
    [
        token(secret="wrong-secret-" + "y" * 32),
        token(exp=int(time.time()) - 10),
        token(type="refresh"),
        token(alg="HS256", sub=None),
        "not-a-jwt",
    ],
)
def test_invalid_tokens_rejected(bad: str) -> None:
    with pytest.raises(HTTPException) as err:
        decode_token(bad, settings())
    assert err.value.status_code == 401


def test_none_algorithm_rejected() -> None:
    unsigned = jwt.encode({"sub": "x", "tenant_id": "t", "exp": time.time() + 60}, None, "none")
    with pytest.raises(HTTPException) as err:
        decode_token(unsigned, settings())
    assert err.value.status_code == 401


def test_token_without_tenant_forbidden() -> None:
    with pytest.raises(HTTPException) as err:
        decode_token(token(tenant_id=None), settings())
    assert err.value.status_code == 403


def test_configurable_tenant_claim() -> None:
    principal = decode_token(
        token(tenant_id=None, org="contoso-life"), settings(tenant_claim="org")
    )
    assert principal.tenant_id == "contoso-life"


def test_issuer_and_audience_enforced_when_configured() -> None:
    strict = settings(jwt_issuer="otterworks-auth", jwt_audience="commission")
    with pytest.raises(HTTPException):
        decode_token(token(), strict)
    ok = token(iss="otterworks-auth", aud="commission")
    assert decode_token(ok, strict).tenant_id == "northwind-mutual"


def test_role_gate() -> None:
    gate = require(MANAGE_RATES)
    viewer = Principal("u", "t", frozenset({"COMMISSION_VIEWER"}))
    with pytest.raises(HTTPException) as err:
        gate(viewer)
    assert err.value.status_code == 403
    admin = Principal("u", "t", frozenset({"COMMISSION_ADMIN"}))
    assert gate(admin) is admin


def test_short_secret_refused() -> None:
    with pytest.raises(ValueError):
        settings(JWT_SECRET="short")


def test_settings_have_no_secret_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("COMMISSION_SVC_DATABASE_URL", raising=False)
    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]
