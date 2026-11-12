"""Authentication middleware for the search service.

Public endpoints (health, metrics) are exempt. Every other request is
authenticated by the service itself; a caller-supplied ``X-User-ID`` header is
never trusted on its own.

* Internal routes (``/index/*`` and ``/reindex``) mutate the shared index and
  are restricted to trusted services holding ``SEARCH_SERVICE_TOKEN``, sent as
  ``Authorization: Bearer <token>``. If no token is configured they are closed.
* User-facing routes require the caller's JWT (forwarded unchanged by the API
  gateway) signed with ``JWT_SECRET``. The user id is taken from the token's
  ``sub`` claim (falling back to ``user_id``); an ``X-User-ID`` header that
  disagrees with the token is rejected. A valid service token is also accepted.
"""

from __future__ import annotations

import hmac

import jwt
import structlog
from flask import g, jsonify, request

logger = structlog.get_logger()

PUBLIC_PREFIXES = ("/health", "/metrics")
INTERNAL_PREFIXES = ("/api/v1/search/index/", "/api/v1/search/reindex")
JWT_ALGORITHMS = ["HS256", "HS384", "HS512"]


def require_auth(app):
    """Register a ``before_request`` hook that enforces authentication."""
    auth_config = app.config["APP_CONFIG"].auth

    @app.before_request
    def _check_auth():
        g.user_id = None
        g.service_caller = False

        path = request.path
        if any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES):
            return None

        token = _extract_bearer_token()
        if _is_service_token(token, auth_config.service_token):
            g.service_caller = True
            return None

        if _is_internal_path(path):
            logger.warning("auth_rejected_internal_route", path=path)
            return _unauthorized()

        if not auth_config.require_auth:
            return None

        user_id = _verify_user_token(token, auth_config.jwt_secret)
        if not user_id:
            logger.warning("auth_rejected", path=path)
            return _unauthorized()

        header_user_id = request.headers.get("X-User-ID", "").strip()
        if header_user_id and header_user_id != user_id:
            logger.warning("auth_rejected_identity_mismatch", path=path)
            return _unauthorized()

        g.user_id = user_id
        return None


def current_user_id() -> str | None:
    """Return the authenticated user id for the current request.

    When authentication is enforced this is the verified JWT subject. With
    ``REQUIRE_AUTH=false`` (local development only) it falls back to the
    ``X-User-ID`` header.
    """
    user_id = g.get("user_id")
    if user_id:
        return user_id
    from flask import current_app

    if not current_app.config["APP_CONFIG"].auth.require_auth:
        return request.headers.get("X-User-ID", "").strip() or None
    return None


def _is_internal_path(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in INTERNAL_PREFIXES)


def _is_service_token(token: str, service_token: str) -> bool:
    if not token or not service_token:
        return False
    return hmac.compare_digest(token.encode(), service_token.encode())


def _verify_user_token(token: str, secret: str) -> str | None:
    if not token or not secret:
        return None
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=JWT_ALGORITHMS,
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError:
        return None
    if claims.get("type") == "refresh":
        return None
    user_id = claims.get("sub") or claims.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        return None
    return user_id.strip()


def _extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _unauthorized():
    return jsonify({"error": "unauthorized"}), 401
