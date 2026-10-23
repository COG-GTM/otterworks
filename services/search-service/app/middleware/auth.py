"""Authentication middleware for the search service.

Public endpoints (health, metrics) are exempt. Every other request must
authenticate itself; nothing the client sends is trusted until it has been
verified here:

* ``Authorization: Bearer <jwt>`` — an access token issued by auth-service
  and verified with ``JWT_SECRET``. The caller's identity (``sub``, falling
  back to ``user_id``) is taken from the verified claims only. The API
  gateway forwards the caller's ``Authorization`` header unchanged, so
  proxied requests carry the token too.
* ``Authorization: Bearer <SEARCH_SERVICE_TOKEN>`` — a service-to-service
  token for trusted internal callers (SQS indexer, admin reindex jobs). It
  carries no user identity, so it can only reach the indexing endpoints,
  never the per-user search endpoints.

The ``X-User-ID`` header is ignored: it can be set by any client that
reaches the service without going through the gateway.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

import jwt
import structlog
from flask import g, jsonify, request

logger = structlog.get_logger()

PUBLIC_PREFIXES = ("/health", "/metrics")

#: auth-service signs with HS512 (jjwt picks the algorithm from the key length).
JWT_ALGORITHMS = ["HS256", "HS384", "HS512"]

#: Endpoints that operate on the whole tenant's index and have no per-user scope.
SERVICE_ONLY_ENDPOINTS = frozenset({"index.reindex"})


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
    """Register a ``before_request`` hook that enforces authentication."""
    auth_config = app.config["APP_CONFIG"].auth

    if auth_config.require_auth and not auth_config.jwt_secret:
        logger.error("jwt_secret_missing", detail="user requests will be rejected until JWT_SECRET is set")

    @app.before_request
    def _check_auth():
        g.principal = None
        if not auth_config.require_auth:
            return None

        path = request.path
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return None

        token = _extract_bearer_token()
        principal = _authenticate(token, auth_config) if token else None
        if principal is None:
            logger.warning("auth_rejected", endpoint=request.endpoint or "", path=path)
            return jsonify({"error": "unauthorized"}), 401

        g.principal = principal
        endpoint = request.endpoint or ""
        if endpoint in SERVICE_ONLY_ENDPOINTS and not principal.is_service:
            logger.warning("auth_forbidden", endpoint=endpoint, path=path, user_id=principal.user_id)
            return jsonify({"error": "forbidden"}), 403
        if principal.is_service and endpoint.startswith("search."):
            # A service token has no user scope; letting it search would return
            # every tenant's documents.
            logger.warning("auth_forbidden", endpoint=endpoint, path=path, caller="service")
            return jsonify({"error": "forbidden"}), 403
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
