"""Service-edge security: JWT authentication, role checks, tenant binding.

Tokens are the auth-service access tokens (HMAC, shared JWT_SECRET) that the
api-gateway already validates and passes through in the Authorization header.
The service re-validates them itself rather than trusting forwarded identity
headers, because the gateway forwards only X-User-ID/X-User-Email (no roles,
no tenant).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.config import Settings

ADMIN_ROLES = frozenset({"ADMIN", "OWNER"})
VIEW = frozenset({"COMMISSION_VIEWER", "COMMISSION_MANAGER", "COMMISSION_ADMIN"}) | ADMIN_ROLES
MANAGE_SPLITS = frozenset({"COMMISSION_MANAGER", "COMMISSION_ADMIN"}) | ADMIN_ROLES
CALCULATE = MANAGE_SPLITS
MANAGE_RATES = frozenset({"COMMISSION_ADMIN"}) | ADMIN_ROLES
PARITY_RESET = frozenset({"COMMISSION_PARITY_RESET"})
RUN_ETL = MANAGE_RATES


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    roles: frozenset[str]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def decode_token(token: str, settings: Settings) -> Principal:
    options: Any = {"require": ["exp"]}
    if not settings.jwt_audience:
        options["verify_aud"] = False
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=settings.jwt_algorithms,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options=options,
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("invalid token") from exc

    if claims.get("type", "access") != "access":
        raise _unauthorized("not an access token")
    subject = claims.get("sub") or claims.get("user_id")
    if not isinstance(subject, str) or not subject:
        raise _unauthorized("token has no subject")
    tenant_id = claims.get(settings.tenant_claim)
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="token is not bound to a tenant")
    raw_roles = claims.get("roles") or []
    if not isinstance(raw_roles, list):
        raise _unauthorized("roles claim must be a list")
    roles = frozenset(str(role).removeprefix("ROLE_").upper() for role in raw_roles)
    return Principal(subject=subject, tenant_id=tenant_id, roles=roles)


def current_principal(request: Request) -> Principal:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("missing bearer token")
    settings: Settings = request.app.state.settings
    return decode_token(token.strip(), settings)


def require(allowed: frozenset[str]) -> Callable[..., Principal]:
    def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if not principal.roles & allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return principal

    return dependency
