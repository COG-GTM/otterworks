"""CSRF protection for state-changing search-service requests.

The search service is a stateless JSON API: callers authenticate with an
``Authorization: Bearer`` service token or the gateway-injected ``X-User-ID``
header, and no session cookie is ever issued. Synchronizer tokens (e.g.
Flask-WTF's ``CSRFProtect``) need a server-side session, so instead every
unsafe request (POST/PUT/PATCH/DELETE) must pass these checks:

* A browser-supplied ``Origin`` must match the request's own host, be one of
  the trusted origins, or be a loopback ``http://`` origin (local shells).
* Without ``Origin``, a ``Sec-Fetch-Site: cross-site`` request is refused.
* A request body must be ``application/json``. HTML forms can only send
  ``application/x-www-form-urlencoded``, ``multipart/form-data`` or
  ``text/plain``, and a cross-origin ``fetch`` with a JSON body needs a CORS
  preflight that only trusted origins pass.

Server-to-server callers (indexers, gateway without a browser ``Origin``)
send none of these browser headers and are unaffected.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import structlog
from flask import jsonify, request

logger = structlog.get_logger()

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
JSON_MIMETYPES = frozenset({"application/json"})


def normalize_origins(origins) -> list[str]:
    """Normalize configured origins the way browsers serialize ``Origin``."""
    return list(dict.fromkeys(_normalize_origin(o) for o in origins if o and o.strip()))


def csrf_protect(app, trusted_origins) -> None:
    """Register a ``before_request`` hook that refuses cross-site writes."""
    trusted = frozenset(normalize_origins(trusted_origins))

    @app.before_request
    def _check_csrf():
        if request.method in SAFE_METHODS:
            return None

        reason = _rejection_reason(trusted)
        if reason is None:
            return None

        logger.warning(
            "csrf_rejected",
            reason=reason,
            method=request.method,
            path=request.path,
            origin=request.headers.get("Origin", ""),
        )
        status = 415 if reason == "unsupported_content_type" else 403
        error = "unsupported_media_type" if status == 415 else "csrf_rejected"
        return jsonify({"error": error}), status


def _rejection_reason(trusted: frozenset[str]) -> str | None:
    origin = request.headers.get("Origin")
    if origin is not None:
        normalized = _normalize_origin(origin)
        if not (
            normalized in trusted
            or _is_same_host(normalized)
            or _is_loopback_http(normalized)
        ):
            return "untrusted_origin"
    elif request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        return "cross_site_request"

    if _has_body() and request.mimetype not in JSON_MIMETYPES:
        return "unsupported_content_type"
    return None


def _has_body() -> bool:
    if request.content_type:
        return True
    if request.content_length:
        return True
    return "chunked" in request.headers.get("Transfer-Encoding", "").lower()


def _is_same_host(normalized_origin: str) -> bool:
    # TLS terminates at the ingress, so only the host (not the scheme) of the
    # proxied request reliably matches the browser's Origin.
    host = urlsplit(normalized_origin).netloc
    return bool(host) and host == _strip_default_port(request.host.lower(), "")


def _is_loopback_http(normalized_origin: str) -> bool:
    # Local shells (e.g. the Electron desktop app on 127.0.0.1:<port>) proxy
    # /api/v1 with the gateway's Host; only local code can serve these origins.
    parts = urlsplit(normalized_origin)
    return parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS


def _normalize_origin(origin: str) -> str:
    origin = origin.strip()
    parts = urlsplit(origin)
    if not parts.scheme or not parts.netloc:
        return origin.lower()
    scheme = parts.scheme.lower()
    return f"{scheme}://{_strip_default_port(parts.netloc.lower(), scheme)}"


def _strip_default_port(host: str, scheme: str) -> str:
    ports = {"http": (":80",), "https": (":443",)}.get(scheme, (":80", ":443"))
    for port in ports:
        if host.endswith(port):
            return host[: -len(port)]
    return host
