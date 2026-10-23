"""QA audit of the Go API gateway (services/api-gateway), black-box through :8080.

Findings referenced here are documented in docs/qa/api-gateway.md.
"""

import base64
import hashlib
import hmac
import http.client
import json
import os
import time
import uuid
from urllib.parse import urlparse

import httpx
import pytest


pytestmark = pytest.mark.api_flow

# Local docker-compose default (docker-compose.yml); override for other stacks.
JWT_SECRET = os.getenv(
    "OTTERWORKS_JWT_SECRET", "otterworks-local-dev-jwt-secret-change-me-in-production"
)

ROUTED_PREFIXES = [
    "/api/v1/auth/profile",
    "/api/v1/settings",
    "/api/v1/files",
    "/api/v1/folders",
    "/api/v1/documents",
    "/api/v1/templates",
    "/api/v1/collab",
    "/api/v1/notifications",
    "/api/v1/preferences",
    "/api/v1/search",
    "/api/v1/analytics",
    "/api/v1/admin",
    "/api/v1/audit",
    "/api/v1/reports",
]

APP_ORIGIN = "http://localhost:3000"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forge_jwt(claims: dict, secret: str = JWT_SECRET, alg: str = "HS256") -> str:
    header = _b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    if alg == "none":
        return f"{header}.{payload}."
    digest = {"HS256": hashlib.sha256, "HS512": hashlib.sha512}[alg]
    sig = _b64(hmac.new(secret.encode(), signing_input, digest).digest())
    return f"{header}.{payload}.{sig}"


def raw_get(base_url: str, path: str, headers: dict | None = None) -> tuple[int, str]:
    """Send a request without client-side path normalisation (httpx collapses //)."""
    parsed = urlparse(base_url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=10)
    try:
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.read().decode(errors="replace")
    finally:
        conn.close()


def secret_matches_gateway(api_client, user) -> bool:
    """True when JWT_SECRET is the one the running gateway uses."""
    token = forge_jwt({"sub": user.id, "exp": int(time.time()) + 300, "type": "access"})
    r = api_client.client.get("/api/v1/documents/", headers={"Authorization": f"Bearer {token}"})
    return r.status_code != 401


@pytest.fixture
def user(api_client):
    return api_client.register_user("qa-gateway")


# ── Health / metrics / request id ───────────────────────────────


def test_health_is_public_json(api_client):
    r = api_client.client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "version": "0.1.0"}


def test_request_id_generated_and_echoed(api_client):
    generated = api_client.client.get("/health").headers.get("x-request-id", "")
    assert len(generated) == 36
    supplied = f"qa-{uuid.uuid4()}"
    echoed = api_client.client.get("/health", headers={"X-Request-ID": supplied})
    assert echoed.headers["x-request-id"] == supplied


def test_metrics_exposed_with_bounded_path_labels(api_client, user):
    marker = uuid.uuid4().hex
    api_client.client.get(f"/api/v1/documents/{marker}", headers=user.auth_headers)
    r = api_client.client.get("/metrics")
    assert r.status_code == 200
    assert "api_gateway_http_requests_total" in r.text
    assert 'path="/api/v1/documents"' in r.text
    assert marker not in r.text, "raw ids must not become metric label values"


@pytest.mark.xfail(reason="QA-GW-04: folders/templates/preferences/reports/settings are labelled 'other' in gateway metrics", strict=True)
def test_metrics_label_for_every_routed_prefix(api_client, user):
    api_client.client.get("/api/v1/folders", headers=user.auth_headers)
    api_client.client.get("/api/v1/settings", headers=user.auth_headers)
    text = api_client.client.get("/metrics").text
    assert 'path="/api/v1/folders"' in text
    assert 'path="/api/v1/settings"' in text


# ── Authentication boundary ─────────────────────────────────────


@pytest.mark.parametrize("path", ROUTED_PREFIXES)
def test_protected_routes_reject_missing_token(api_client, path):
    r = api_client.client.get(path)
    assert r.status_code == 401, f"{path}: {r.status_code} {r.text}"
    body = api_client.assert_json_error(r)
    assert "authorization" in body["error"]


@pytest.mark.parametrize(
    "header",
    [
        "Bearer garbage",
        "Bearer a.b.c",
        "Bearer",
        "Basic dXNlcjpwYXNz",
        "Token abc",
    ],
    ids=["garbage", "three-parts", "empty", "basic", "unknown-scheme"],
)
def test_protected_routes_reject_malformed_credentials(api_client, header):
    r = api_client.client.get("/api/v1/files", headers={"Authorization": header})
    assert r.status_code == 401
    api_client.assert_json_error(r)


def test_public_auth_endpoints_reachable_without_token(api_client, user):
    login = api_client.client.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
    assert login.status_code == 200
    # Validation errors come from auth-service, proving the gateway let the request through.
    bad = api_client.client.post("/api/v1/auth/register", json={})
    assert bad.status_code == 400


def test_public_exact_paths_do_not_extend_to_siblings(api_client):
    for path in ("/api/v1/auth/login/", "/api/v1/auth/users", "/api/v1/auth/users/lookup?email=x@y.z"):
        r = api_client.client.get(path)
        assert r.status_code == 401, f"{path} -> {r.status_code}"


def test_valid_token_reaches_backends(api_client, user):
    for path in ("/api/v1/auth/profile", "/api/v1/files", "/api/v1/documents/"):
        r = api_client.client.get(path, headers=user.auth_headers)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
    assert api_client.client.get("/api/v1/auth/profile", headers=user.auth_headers).json()["email"] == user.email


def test_forged_tokens_rejected(api_client, user):
    now = int(time.time())
    base = {"sub": user.id, "email": user.email, "type": "access"}
    tokens = {
        "wrong-secret": forge_jwt({**base, "exp": now + 600}, secret="not-the-secret"),
        "alg-none": forge_jwt({**base, "exp": now + 600}, alg="none"),
        "tampered": user.access_token[:-4] + ("AAAA" if not user.access_token.endswith("AAAA") else "BBBB"),
    }
    for name, token in tokens.items():
        r = api_client.client.get("/api/v1/files", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, f"{name}: {r.status_code} {r.text}"


def test_expired_token_rejected(api_client, user):
    if not secret_matches_gateway(api_client, user):
        pytest.skip("OTTERWORKS_JWT_SECRET does not match the running gateway")
    now = int(time.time())
    token = forge_jwt({"sub": user.id, "type": "access", "iat": now - 7200, "exp": now - 3600})
    r = api_client.client.get("/api/v1/files", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "expired" in r.json()["error"]


def test_double_slash_and_dot_segments_do_not_bypass_auth(api_client, base_url):
    for path in ("//api/v1/files", "/api//v1/files", "/./api/v1/files", "/health/../api/v1/files", "/socket.io/../api/v1/files"):
        status, body = raw_get(base_url, path)
        assert status != 200 or '"items"' not in body and '"files"' not in body, f"{path} -> {status} {body[:200]}"
        assert status in {301, 400, 401, 404, 502, 503}, f"{path} -> {status} {body[:200]}"


@pytest.mark.xfail(reason="QA-GW-01: gateway accepts a type=refresh JWT as an access token", strict=True)
def test_refresh_token_cannot_be_used_as_access_token(api_client, user):
    r = api_client.client.get("/api/v1/documents/", headers={"Authorization": f"Bearer {user.refresh_token}"})
    assert r.status_code == 401, r.text


@pytest.mark.xfail(reason="QA-GW-02: gateway accepts JWTs without an exp claim", strict=True)
def test_token_without_expiry_rejected(api_client, user):
    if not secret_matches_gateway(api_client, user):
        pytest.skip("OTTERWORKS_JWT_SECRET does not match the running gateway")
    token = forge_jwt({"sub": user.id, "email": user.email, "type": "access"})
    r = api_client.client.get("/api/v1/documents/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, r.text


# ── Trusted identity headers ────────────────────────────────────


def test_spoofed_identity_headers_cannot_access_other_users_data(api_client):
    owner = api_client.register_user("qa-gw-owner")
    intruder = api_client.register_user("qa-gw-intruder")
    doc = api_client.create_document(owner, "qa-gateway private", "owner only")

    spoof = {**intruder.auth_headers, "X-User-ID": owner.id, "X-User-Email": owner.email}
    r = api_client.client.get(f"/api/v1/documents/{doc['id']}", headers=spoof)
    assert r.status_code in {403, 404}, r.text

    listing = api_client.client.get("/api/v1/documents/", headers=spoof)
    assert listing.status_code == 200
    assert doc["id"] not in listing.text

    # The legitimate owner still sees it.
    assert api_client.client.get(f"/api/v1/documents/{doc['id']}", headers=owner.auth_headers).status_code == 200


def test_spoofed_identity_header_without_token_is_rejected(api_client, user):
    r = api_client.client.get("/api/v1/files", headers={"X-User-ID": user.id})
    assert r.status_code == 401


# ── CORS ───────────────────────────────────────────────────────


def test_cors_preflight_for_app_origin(api_client):
    r = api_client.client.options(
        "/api/v1/documents/",
        headers={"Origin": APP_ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"},
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == APP_ORIGIN
    assert r.headers["access-control-allow-credentials"] == "true"
    assert "Authorization" in r.headers["access-control-allow-headers"]
    assert "POST" in r.headers["access-control-allow-methods"]


def test_cors_rejects_foreign_origin(api_client):
    r = api_client.client.options(
        "/api/v1/documents/", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in r.headers
    assert r.status_code == 401, "foreign preflight falls through to the auth check"


def test_401_is_readable_by_app_origin(api_client):
    r = api_client.client.get("/api/v1/files", headers={"Origin": APP_ORIGIN})
    assert r.status_code == 401
    assert r.headers.get("access-control-allow-origin") == APP_ORIGIN


# ── Routing and upstream failure ────────────────────────────────


def test_unknown_route_returns_json_404(api_client):
    r = api_client.client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": "route not found"}


def _upstream_down_prefix(api_client, user) -> str:
    for prefix in ("/api/v1/reports", "/api/v1/audit", "/api/v1/analytics"):
        r = api_client.client.get(f"{prefix}/qa-probe", headers=user.auth_headers)
        if r.status_code in {502, 503}:
            return prefix
    pytest.skip("every optional backend is running; cannot exercise upstream-down path")


def test_upstream_down_returns_502_then_circuit_503(api_client, user):
    prefix = _upstream_down_prefix(api_client, user)
    statuses = []
    for _ in range(8):
        r = api_client.client.get(f"{prefix}/qa-probe", headers=user.auth_headers)
        statuses.append(r.status_code)
        body = api_client.assert_json_error(r)
        assert "unavailable" in body["error"]
        assert "service-" not in r.text and ":80" not in r.text, "internal upstream address leaked"
    assert set(statuses) <= {502, 503}, statuses
    assert statuses[-1] == 503, f"circuit breaker should be open after repeated failures: {statuses}"
    assert api_client.client.get(f"{prefix}/qa-probe", headers=user.auth_headers).json()["reason"] == "circuit breaker open"
    # A healthy route is unaffected by another route's open circuit.
    assert api_client.client.get("/api/v1/auth/profile", headers=user.auth_headers).status_code == 200


# ── Rate limiting ───────────────────────────────────────────────


def _burst(client: httpx.Client, n: int, headers_for) -> list[int]:
    return [client.get("/health", headers=headers_for(i)).status_code for i in range(n)]


@pytest.mark.skipif(os.getenv("OTTERWORKS_QA_SKIP_RATE_LIMIT") == "1", reason="rate limit probes disabled")
def test_rate_limit_returns_429(api_client):
    time.sleep(1.1)
    codes = _burst(api_client.client, 400, lambda i: {})
    time.sleep(1.1)  # let the bucket refill for later tests
    if 429 not in codes:
        pytest.skip("could not exceed RATE_LIMIT_RPS from a single client in this environment")
    r429 = codes.index(429)
    assert r429 > 0


@pytest.mark.xfail(reason="QA-GW-03: rate limiter keyed on client-controlled X-Forwarded-For/X-Real-IP", strict=True)
@pytest.mark.skipif(os.getenv("OTTERWORKS_QA_SKIP_RATE_LIMIT") == "1", reason="rate limit probes disabled")
def test_rate_limit_not_bypassed_by_rotating_forwarded_for(api_client):
    time.sleep(1.1)
    codes = _burst(api_client.client, 400, lambda i: {"X-Forwarded-For": f"203.0.{i // 250}.{i % 250}"})
    time.sleep(1.1)
    assert 429 in codes, "rotating X-Forwarded-For evaded the per-IP limiter"
