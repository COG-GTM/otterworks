from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import time
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException

from app.config import settings

MIN_SECRET_LENGTH = 32
CLOCK_SKEW_SECONDS = 30
# The platform issuer (JJWT signWith(key)) picks the HMAC size from the secret length.
HMAC_ALGORITHMS = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}


@dataclass(frozen=True)
class Caller:
    subject: str
    roles: frozenset[str]
    tenant_id: UUID | None

    @property
    def is_admin(self) -> bool:
        return not self.roles.isdisjoint(settings.admin_roles)


class InvalidTokenError(Exception):
    pass


def _b64decode(segment: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError) as error:
        raise InvalidTokenError("malformed token") from error


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _json_segment(segment: str) -> dict:
    try:
        value = json.loads(_b64decode(segment))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidTokenError("malformed token") from error
    if not isinstance(value, dict):
        raise InvalidTokenError("malformed token")
    return value


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def encode_token(claims: dict, secret: str, alg: str = "HS256") -> str:
    header = _b64encode(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64encode(json.dumps(claims).encode())
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), HMAC_ALGORITHMS[alg])
    return f"{header}.{payload}.{_b64encode(signature.digest())}"


def decode_token(token: str, secret: str, now: float | None = None) -> dict:
    """Verify an HMAC-signed (HS256/384/512) platform access token and return its claims."""
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidTokenError("malformed token")
    header_segment, payload_segment, signature_segment = parts
    header = _json_segment(header_segment)
    alg = header.get("alg")
    digest = HMAC_ALGORITHMS.get(alg) if isinstance(alg, str) else None
    if digest is None:
        raise InvalidTokenError("unsupported token algorithm")
    expected = hmac.new(
        secret.encode(), f"{header_segment}.{payload_segment}".encode(), digest
    ).digest()
    if not hmac.compare_digest(expected, _b64decode(signature_segment)):
        raise InvalidTokenError("invalid token signature")
    claims = _json_segment(payload_segment)
    current = time.time() if now is None else now
    exp = claims.get("exp")
    if not _is_number(exp):
        raise InvalidTokenError("token has no expiry")
    if current > exp + CLOCK_SKEW_SECONDS:
        raise InvalidTokenError("token expired")
    nbf = claims.get("nbf")
    if nbf is not None and not _is_number(nbf):
        raise InvalidTokenError("invalid not-before")
    if nbf is not None and current + CLOCK_SKEW_SECONDS < nbf:
        raise InvalidTokenError("token not yet valid")
    if claims.get("type") != "access":
        raise InvalidTokenError("not an access token")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise InvalidTokenError("token has no subject")
    return claims


def _caller_from_claims(claims: dict) -> Caller:
    roles = claims.get("roles") or []
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise InvalidTokenError("invalid roles claim")
    raw_tenant = claims.get("tenant_id")
    tenant_id = None
    if raw_tenant is not None:
        try:
            tenant_id = UUID(str(raw_tenant))
        except ValueError as error:
            raise InvalidTokenError("invalid tenant_id claim") from error
    return Caller(subject=claims["sub"], roles=frozenset(roles), tenant_id=tenant_id)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def require_caller(
    authorization: Annotated[str | None, Header()] = None,
) -> Caller:
    secret = settings.jwt_secret
    if len(secret) < MIN_SECRET_LENGTH:
        raise HTTPException(status_code=503, detail="authentication is not configured")
    if not authorization:
        raise _unauthorized("authentication required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("authentication required")
    try:
        return _caller_from_claims(decode_token(token.strip(), secret))
    except InvalidTokenError as error:
        raise _unauthorized("invalid or expired token") from error


def authorize_tenant(caller: Caller, tenant_id: UUID) -> None:
    if caller.is_admin or caller.tenant_id == tenant_id:
        return
    raise HTTPException(status_code=403, detail="not permitted for this tenant")


def require_internal_reset_token(
    x_internal_reset_token: Annotated[str | None, Header()] = None,
) -> None:
    configured = settings.internal_reset_token
    if not settings.allow_internal_reset or len(configured) < MIN_SECRET_LENGTH:
        raise HTTPException(status_code=404, detail="internal reset is disabled")
    if not x_internal_reset_token or not hmac.compare_digest(
        x_internal_reset_token.encode(), configured.encode()
    ):
        raise HTTPException(status_code=403, detail="internal reset token required")


CallerDep = Annotated[Caller, Depends(require_caller)]
