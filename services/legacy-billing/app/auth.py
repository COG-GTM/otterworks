"""Bearer-token authentication and tenant authorization for legacy-billing.

Tokens are HS256 JWTs signed with the platform JWT secret, the same scheme the
auth-service issues and the api-gateway verifies. Billing access is granted by
two extra claims:

- ``scope``: space-separated scopes (``billing:read``, ``billing:write``,
  ``billing:admin``); a list under ``scp`` is also accepted.
- ``tenant_id``: the tenant the caller acts for. Required for tenant-scoped
  routes unless the caller holds ``billing:admin``.
"""

import base64
import binascii
import functools
import hashlib
import hmac
import json
import math
import re
import time
import uuid

from flask import abort, current_app, g, request

READ = "billing:read"
WRITE = "billing:write"
ADMIN = "billing:admin"
MIN_SECRET_BYTES = 32
CLOCK_SKEW_SECONDS = 30
SEGMENT = re.compile(r"[A-Za-z0-9_-]+\Z")


class InvalidToken(Exception):
    pass


def _b64decode(segment):
    padded = segment + "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as error:
        raise InvalidToken("malformed token") from error


def _json_segment(segment):
    try:
        value = json.loads(_b64decode(segment))
    except (UnicodeDecodeError, ValueError) as error:
        raise InvalidToken("malformed token") from error
    if not isinstance(value, dict):
        raise InvalidToken("malformed token")
    return value


def _numeric(claims, name, required=False):
    value = claims.get(name)
    if value is None:
        if required:
            raise InvalidToken(f"missing {name}")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidToken(f"invalid {name}")
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidToken(f"invalid {name}")
    return value


def decode_token(token, secret, now=None):
    parts = token.split(".")
    if len(parts) != 3 or not all(SEGMENT.match(part) for part in parts):
        raise InvalidToken("malformed token")
    header = _json_segment(parts[0])
    if header.get("alg") != "HS256":
        raise InvalidToken("unsupported algorithm")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64decode(parts[2])):
        raise InvalidToken("bad signature")
    claims = _json_segment(parts[1])
    now = time.time() if now is None else now
    if _numeric(claims, "exp", required=True) <= now - CLOCK_SKEW_SECONDS:
        raise InvalidToken("token expired")
    nbf = _numeric(claims, "nbf")
    if nbf is not None and nbf > now + CLOCK_SKEW_SECONDS:
        raise InvalidToken("token not yet valid")
    if claims.get("type", "access") != "access":
        raise InvalidToken("not an access token")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise InvalidToken("missing sub")
    return claims


def scopes(claims):
    raw = claims.get("scope", "")
    granted = set(raw.split()) if isinstance(raw, str) else set()
    listed = claims.get("scp", [])
    if isinstance(listed, list):
        granted.update(item for item in listed if isinstance(item, str))
    if ADMIN in granted:
        granted.update({READ, WRITE})
    if WRITE in granted:
        granted.add(READ)
    return granted


def parse_tenant(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _bearer_token():
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def authenticate():
    secret = current_app.config.get("JWT_SECRET") or ""
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        current_app.logger.error("LEGACY_BILLING_JWT_SECRET is unset or shorter than %d bytes", MIN_SECRET_BYTES)
        abort(503, description="authentication is not configured")
    token = _bearer_token()
    if not token:
        abort(401, description="missing bearer token")
    try:
        return decode_token(token, secret)
    except InvalidToken as error:
        abort(401, description=str(error))


def authorize_tenant(tenant_id):
    """Abort unless the authenticated caller may act for ``tenant_id``."""
    if ADMIN in g.billing_scopes:
        return
    caller = parse_tenant(g.billing_claims.get("tenant_id"))
    if caller is None or caller != parse_tenant(tenant_id):
        abort(403, description="tenant not permitted")


def public(view):
    view.billing_policy = "public"
    return view


def requires(scope, tenant=None):
    """Require ``scope``; when ``tenant`` is given, also authorize the tenant it returns.

    ``tenant`` receives the view kwargs and returns the tenant id to authorize.
    """

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            claims = authenticate()
            g.billing_claims = claims
            g.billing_scopes = scopes(claims)
            if scope not in g.billing_scopes:
                abort(403, description=f"{scope} scope required")
            if tenant is not None:
                tenant_id = tenant(kwargs)
                if parse_tenant(tenant_id) is None:
                    abort(400, description="tenant_id must be a UUID")
                authorize_tenant(tenant_id)
            return view(*args, **kwargs)

        wrapper.billing_policy = scope
        return wrapper

    return decorator


def enforce_declared_policy():
    """Fail closed for any route registered without a ``requires``/``public`` policy."""
    if request.endpoint is None:
        return
    view = current_app.view_functions.get(request.endpoint)
    if getattr(view, "billing_policy", None) is None:
        abort(403)
