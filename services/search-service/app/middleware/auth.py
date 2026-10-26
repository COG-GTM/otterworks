"""Authentication middleware for the search service.

Public endpoints (health, metrics) are exempt. Every other request must
authenticate itself here; nothing a client sends is trusted until it has been
verified:

* ``Authorization: Bearer <jwt>`` -- an access token issued by auth-service,
  verified with ``JWT_SECRET``. The caller's identity is taken from the
  verified ``sub`` claim (falling back to ``user_id``). The API gateway
  forwards the caller's ``Authorization`` header unchanged, so requests
  proxied through it carry the token too.
* ``Authorization: Bearer <SEARCH_SERVICE_TOKEN>`` -- a service-to-service
  token for trusted internal callers (SQS indexer, admin reindex jobs). It
  carries no user identity, so it cannot run per-user searches.

Writing to the index, reindexing and the cross-user analytics are not scoped to
one user, so only the service token may call them; user tokens get 403.

The ``X-User-ID`` header is never trusted: any client that reaches the
service without going through the gateway can set it.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

import jwt
import structlog
from flask import g, jsonify, request

logger = structlog.get_logger()

PUBLIC_PREFIXES = ("/health", "/metrics")

#: Blueprints and endpoints that act on every user's data and need the service token.
SERVICE_ONLY_BLUEPRINTS = frozenset({"index"})
SERVICE_ONLY_ENDPOINTS = frozenset({"search.search_analytics"})

#: auth-service signs with jjwt, which picks the HMAC strength from the key length.
JWT_ALGORITHMS = ["HS256", "HS384", "HS512"]


@dataclass(frozen=True)
class Principal:
    """The authenticated caller of the current request."""

    user_id: str | None = None
    is_service: bool = False


def current_principal() -> Principal:
    """Return the caller authenticated by ``require_auth`` for this request."""
    return g.get("principal") or Principal()


def current_user_id() -> str | None:
    """Return the verified user id of the caller, or None for service callers."""
    return current_principal().user_id


def require_auth(app):
    """Register a ``before_request`` hook that authenticates every non-public request."""
    auth_config = app.config["APP_CONFIG"].auth

    if not auth_config.jwt_secret:
        logger.error("jwt_secret_missing", detail="user requests are rejected until JWT_SECRET is set")

    @app.before_request
    def _check_auth():
        g.principal = None
        path = request.path
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return None

        token = _extract_bearer_token()
        principal = _authenticate(token, auth_config) if token else None
        if principal is None:
            logger.warning("auth_rejected", endpoint=request.endpoint or "", path=path)
            return jsonify({"error": "unauthorized"}), 401

        g.principal = principal
        if not principal.is_service and (
            request.blueprint in SERVICE_ONLY_BLUEPRINTS or request.endpoint in SERVICE_ONLY_ENDPOINTS
        ):
            logger.warning("service_token_required", endpoint=request.endpoint or "", path=path)
            return jsonify({"error": "a service token is required"}), 403
        return None


def _authenticate(token: str, auth_config) -> Principal | None:
    if auth_config.service_token and hmac.compare_digest(
        token.encode(), auth_config.service_token.encode()
    ):
        return Principal(is_service=True)

    if not auth_config.jwt_secret:
        return None
    try:
        claims = jwt.decode(
            token,
            auth_config.jwt_secret,
            algorithms=JWT_ALGORITHMS,
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError as exc:
        logger.info("jwt_rejected", reason=type(exc).__name__)
        return None

    if claims.get("type") == "refresh":
        return None
    user_id = str(claims.get("sub") or claims.get("user_id") or "").strip()
    if not user_id:
        return None
    return Principal(user_id=user_id)


def _extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""
