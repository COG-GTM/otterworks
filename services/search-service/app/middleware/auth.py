"""Authentication middleware for the search service.

Public endpoints (health, metrics) are exempt. All other endpoints accept
either of two authentication modes:

* A valid service-to-service token via ``Authorization: Bearer <token>``
  (used by trusted internal callers such as the SQS indexer or admin
  reindex jobs).
* The ``X-User-ID`` header injected by the API gateway after it has
  validated the caller's JWT (used by user-facing requests proxied
  through the gateway).

If a service token is configured the middleware will accept it on any
endpoint; if it is not configured (e.g. local dev), only the gateway
identity path is available.

Index-mutation endpoints are stricter: :func:`require_service_token`
accepts only the service token, regardless of ``REQUIRE_AUTH``, and
rejects every request when no token is configured.
"""

from __future__ import annotations

import hmac
from functools import wraps

import structlog
from flask import current_app, jsonify, request

logger = structlog.get_logger()

PUBLIC_PREFIXES = ("/health", "/metrics")


def require_auth(app):
    """Register a ``before_request`` hook that enforces authentication.

    * Requests to health/metrics paths are always allowed.
    * All other requests must present either a valid service token in
      the ``Authorization`` header or an ``X-User-ID`` header set by
      the API gateway after JWT validation.
    """
    auth_config = app.config["APP_CONFIG"].auth

    @app.before_request
    def _check_auth():
        if not auth_config.require_auth:
            return None

        path = request.path
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return None

        # Accept a valid service token if one is configured.
        if auth_config.service_token:
            token = _extract_bearer_token()
            if _token_matches(token, auth_config.service_token):
                return None

        # Otherwise require gateway-injected user identity.
        user_id = request.headers.get("X-User-ID", "").strip()
        if user_id:
            return None

        endpoint = request.endpoint or ""
        logger.warning("auth_rejected", endpoint=endpoint, path=path)
        return jsonify({"error": "unauthorized"}), 401


def _extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _token_matches(presented: str, expected: str) -> bool:
    if not presented or not expected:
        return False
    return hmac.compare_digest(presented.encode(), expected.encode())


def require_service_token(view):
    """Restrict *view* to callers presenting the service token.

    Gateway users (``X-User-ID``) get 403. Without a configured token the
    endpoint is closed to everyone.
    """

    @wraps(view)
    def _wrapped(*args, **kwargs):
        service_token = current_app.config["APP_CONFIG"].auth.service_token
        presented = _extract_bearer_token()
        if _token_matches(presented, service_token):
            return view(*args, **kwargs)

        if not service_token:
            logger.warning("service_token_not_configured", path=request.path)
        if presented or request.headers.get("X-User-ID", "").strip():
            logger.warning("service_auth_forbidden", path=request.path)
            return jsonify({"error": "forbidden"}), 403
        logger.warning("service_auth_rejected", path=request.path)
        return jsonify({"error": "unauthorized"}), 401

    return _wrapped
