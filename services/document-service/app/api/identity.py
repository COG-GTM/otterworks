"""Caller identity resolution shared by the API routers."""

import os
from uuid import UUID

import jwt
from fastapi import Request


def _get_jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "")


def _jwt_claims(request: Request) -> dict | None:
    """Return the verified claims of the bearer JWT, or None."""
    auth_header = request.headers.get("Authorization")
    if not (auth_header and auth_header.startswith("Bearer ")):
        return None
    secret = _get_jwt_secret()
    if not secret:
        return None
    try:
        return jwt.decode(auth_header[len("Bearer "):], secret, algorithms=["HS256", "HS384"])
    except jwt.PyJWTError:
        return None


def _extract_user_id(request: Request) -> UUID | None:
    """Extract user ID from the Authorization JWT."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        if _get_jwt_secret():
            payload = _jwt_claims(request)
            user_id_str = payload and (payload.get("user_id") or payload.get("sub"))
            if user_id_str:
                try:
                    return UUID(str(user_id_str))
                except ValueError:
                    pass
        else:
            forwarded_user_id = request.headers.get("X-User-ID")
            if forwarded_user_id:
                try:
                    return UUID(str(forwarded_user_id))
                except ValueError:
                    pass

    return None
