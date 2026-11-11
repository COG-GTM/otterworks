from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _is_service_token(token: str) -> bool:
    expected = settings.service_token
    return bool(expected) and hmac.compare_digest(token.encode(), expected.encode())


def require_service_caller(credentials: Credentials) -> None:
    if credentials is None:
        raise _unauthorized("authentication required")
    if not _is_service_token(credentials.credentials):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def require_tenant_access(
    tenant_id: Annotated[UUID, Path()],
    credentials: Credentials,
) -> UUID:
    if credentials is None:
        raise _unauthorized("authentication required")
    token = credentials.credentials
    if _is_service_token(token):
        return tenant_id
    if not settings.jwt_secret:
        raise _unauthorized("invalid token")
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as error:
        raise _unauthorized("invalid token") from error
    try:
        caller_tenant = UUID(str(claims.get("tenant_id")))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden") from error
    if caller_tenant != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return tenant_id
