import base64
import hashlib
import hmac
import json
import time

import app as legacy
import auth
import pytest
from flask import Flask

SECRET = "test-secret-that-is-at-least-32-bytes-long"
TENANT = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
INVOICE = "40000000-0000-0000-0000-000000000001"
PERIOD = {"period_start": "2026-02-01", "period_end": "2026-02-28"}


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint(secret=SECRET, alg="HS256", **overrides):
    claims = {"sub": "user-1", "type": "access", "exp": int(time.time()) + 300}
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    header = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    signature = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{b64(signature)}"


def bearer(**claims):
    return {"Authorization": f"Bearer {mint(**claims)}"}


def tenant_reader(tenant=TENANT):
    return bearer(scope=auth.READ, tenant_id=tenant)


def tenant_writer(tenant=TENANT):
    return bearer(scope=auth.WRITE, tenant_id=tenant)


def billing_admin():
    return bearer(scope=auth.ADMIN)


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def fake_execute(sql, params=()):
        recorded.append((sql, params))

    def fake_select(sql, params=()):
        recorded.append((sql, params))
        if "FROM billing.invoices WHERE id" in sql:
            return [{"tenant_id": TENANT}] if params == (INVOICE,) else []
        return [{"ok": True}]

    monkeypatch.setattr(legacy, "execute", fake_execute)
    monkeypatch.setattr(legacy, "select", fake_select)
    return recorded


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(legacy.app.config, "JWT_SECRET", SECRET)
    return legacy.app.test_client()


def procedure_calls(calls):
    return [call for call in calls if "FROM billing.invoices WHERE id" not in call[0]]


# (method, path, kwargs) for every route except /health.
ROUTES = [
    ("get", "/", {}),
    ("get", "/plans", {}),
    ("get", f"/plans/{TENANT}/entitlement", {}),
    ("post", f"/plans/{TENANT}/change", {"data": {"plan_id": "p", "effective_on": "2026-03-01"}}),
    ("post", "/api/rating/preview", {"json": {"tenant_id": TENANT, **PERIOD}}),
    ("post", "/api/rating/finalize", {"json": {"tenant_id": TENANT, **PERIOD}}),
    ("get", f"/api/invoices/{TENANT}/preview", {}),
    ("post", f"/api/invoices/{TENANT}/issue", {"data": PERIOD}),
    ("get", f"/api/invoices/{INVOICE}/lines", {}),
    ("get", "/api/dunning/overdue", {}),
    ("post", "/api/dunning/schedule", {"data": {"as_of": "2026-02-28"}}),
    ("post", "/api/dunning/suspend", {"data": {"as_of": "2026-02-28"}}),
]
ROUTE_IDS = [f"{method.upper()} {path}" for method, path, _ in ROUTES]

# Same routes, but targeting another tenant's data.
CROSS_TENANT = [
    ("get", f"/plans/{OTHER}/entitlement", {}, tenant_reader),
    ("post", f"/plans/{OTHER}/change", {"data": {"plan_id": "p", "effective_on": "2026-03-01"}}, tenant_writer),
    ("post", "/api/rating/preview", {"json": {"tenant_id": OTHER, **PERIOD}}, tenant_reader),
    ("get", f"/api/invoices/{OTHER}/preview", {}, tenant_reader),
]

ADMIN_ONLY = [
    ("post", "/api/rating/finalize", {"json": {"tenant_id": TENANT, **PERIOD}}),
    ("post", f"/api/invoices/{TENANT}/issue", {"data": PERIOD}),
    ("get", "/api/dunning/overdue", {}),
    ("post", "/api/dunning/schedule", {"data": {"as_of": "2026-02-28"}}),
    ("post", "/api/dunning/suspend", {"data": {"as_of": "2026-02-28"}}),
]


@pytest.mark.parametrize(("method", "path", "kwargs"), ROUTES, ids=ROUTE_IDS)
def test_anonymous_requests_are_rejected(client, calls, method, path, kwargs):
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")
    assert calls == []


@pytest.mark.parametrize(("method", "path", "kwargs"), ROUTES, ids=ROUTE_IDS)
def test_billing_admin_can_call_every_route(client, calls, method, path, kwargs):
    response = getattr(client, method)(path, headers=billing_admin(), **kwargs)
    assert response.status_code in (200, 302)
    assert procedure_calls(calls)


@pytest.mark.parametrize(("method", "path", "kwargs", "headers"), CROSS_TENANT)
def test_cross_tenant_access_is_forbidden(client, calls, method, path, kwargs, headers):
    response = getattr(client, method)(path, headers=headers(TENANT), **kwargs)
    assert response.status_code == 403
    assert calls == []


@pytest.mark.parametrize(("method", "path", "kwargs", "headers"), CROSS_TENANT)
def test_own_tenant_access_is_allowed(client, calls, method, path, kwargs, headers):
    path = path.replace(OTHER, TENANT)
    if "json" in kwargs:
        kwargs = {"json": {**kwargs["json"], "tenant_id": TENANT}}
    response = getattr(client, method)(path, headers=headers(TENANT), **kwargs)
    assert response.status_code in (200, 302)
    assert calls[0][1][0] == TENANT


@pytest.mark.parametrize(("method", "path", "kwargs"), ADMIN_ONLY)
def test_operator_actions_require_admin_scope(client, calls, method, path, kwargs):
    response = getattr(client, method)(path, headers=tenant_writer(TENANT), **kwargs)
    assert response.status_code == 403
    assert calls == []


def test_plan_change_requires_write_scope(client, calls):
    form = {"plan_id": "p", "effective_on": "2026-03-01"}
    response = client.post(f"/plans/{TENANT}/change", data=form, headers=tenant_reader(TENANT))
    assert response.status_code == 403
    assert calls == []


def test_plan_change_for_own_tenant_calls_procedure(client, calls):
    form = {"plan_id": "p", "effective_on": "2026-03-01"}
    response = client.post(f"/plans/{TENANT}/change", data=form, headers=tenant_writer(TENANT))
    assert response.status_code == 302
    assert calls == [("CALL billing.sp_change_plan(%s, %s, %s)", (TENANT, "p", "2026-03-01"))]


def test_tenant_comparison_is_case_insensitive(client, calls):
    response = client.get(f"/plans/{TENANT.upper()}/entitlement", headers=tenant_reader(TENANT))
    assert response.status_code == 200


def test_invoice_lines_of_another_tenant_are_not_found(client, calls):
    response = client.get(f"/api/invoices/{INVOICE}/lines", headers=tenant_reader(OTHER))
    assert response.status_code == 404
    assert procedure_calls(calls) == []


def test_invoice_lines_of_own_tenant_are_returned(client, calls):
    response = client.get(f"/api/invoices/{INVOICE}/lines", headers=tenant_reader(TENANT))
    assert response.status_code == 200
    assert procedure_calls(calls) == [("SELECT * FROM billing.fn_invoice_lines(%s)", (INVOICE,))]


def test_unknown_or_malformed_invoice_is_not_found(client, calls):
    unknown = "40000000-0000-0000-0000-000000000099"
    assert client.get(f"/api/invoices/{unknown}/lines", headers=billing_admin()).status_code == 404
    assert client.get("/api/invoices/not-a-uuid/lines", headers=billing_admin()).status_code == 404
    assert procedure_calls(calls) == []


def test_token_without_tenant_claim_cannot_use_tenant_routes(client, calls):
    response = client.get(f"/plans/{TENANT}/entitlement", headers=bearer(scope=auth.READ))
    assert response.status_code == 403


def test_token_without_billing_scope_is_forbidden(client, calls):
    response = client.get("/plans", headers=bearer(tenant_id=TENANT, roles=["ADMIN"]))
    assert response.status_code == 403
    assert calls == []


def test_scp_list_claim_is_accepted(client, calls):
    response = client.get("/plans", headers=bearer(scp=[auth.READ]))
    assert response.status_code == 200


def test_non_uuid_tenant_is_rejected(client, calls):
    response = client.get("/plans/not-a-uuid/entitlement", headers=billing_admin())
    assert response.status_code == 400
    assert calls == []


def test_rating_requires_json_object(client, calls):
    response = client.post("/api/rating/preview", data="x", content_type="text/plain", headers=billing_admin())
    assert response.status_code == 400
    assert calls == []


@pytest.mark.parametrize(
    "token",
    [
        mint(secret="another-secret-that-is-also-32-bytes-long", scope=auth.ADMIN),
        mint(alg="none", scope=auth.ADMIN),
        mint(alg="HS512", scope=auth.ADMIN),
        mint(scope=auth.ADMIN, exp=int(time.time()) - 3600),
        mint(scope=auth.ADMIN, exp=None),
        mint(scope=auth.ADMIN, exp="never"),
        mint(scope=auth.ADMIN, nbf=int(time.time()) + 3600),
        mint(scope=auth.ADMIN, type="refresh"),
        mint(scope=auth.ADMIN, sub=None),
        mint(scope=auth.ADMIN).rsplit(".", 1)[0] + ".",
        mint(scope=auth.ADMIN).rsplit(".", 1)[0],
        "not-a-jwt",
        "eyJhbGciOiJIUzI1NiJ9.\u00e9.sig",
        mint(scope=auth.ADMIN).replace(".", "=.", 1),
        mint(scope=auth.ADMIN, exp=float("nan")),
        mint(scope=auth.ADMIN, exp=float("inf")),
        mint(scope=auth.ADMIN, nbf=float("-inf")),
        mint(scope=auth.ADMIN, exp=-(10**309)),
        mint(scope=auth.ADMIN, nbf=10**309),
    ],
    ids=[
        "wrong-secret",
        "alg-none",
        "alg-hs512",
        "expired",
        "no-exp",
        "bad-exp",
        "nbf-future",
        "refresh",
        "no-sub",
        "empty-sig",
        "two-parts",
        "garbage",
        "non-ascii-payload",
        "padded-segment",
        "nan-exp",
        "infinite-exp",
        "infinite-nbf",
        "huge-negative-int-exp",
        "huge-int-nbf",
    ],
)
def test_invalid_tokens_are_rejected(client, calls, token):
    response = client.post(
        "/api/dunning/suspend", data={"as_of": "2026-02-28"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert calls == []


def test_tampered_claims_are_rejected(client, calls):
    header, _, signature = mint(scope=auth.READ, tenant_id=TENANT).split(".")
    forged = b64(json.dumps({"sub": "user-1", "exp": int(time.time()) + 300, "scope": auth.ADMIN}).encode())
    response = client.get("/api/dunning/overdue", headers={"Authorization": f"Bearer {header}.{forged}.{signature}"})
    assert response.status_code == 401


@pytest.mark.parametrize("secret", ["", "too-short"])
def test_missing_or_weak_secret_fails_closed(client, calls, monkeypatch, secret):
    monkeypatch.setitem(legacy.app.config, "JWT_SECRET", secret)
    response = client.get("/plans", headers=bearer(secret=secret or "x", scope=auth.ADMIN))
    assert response.status_code == 503
    assert calls == []


def test_health_stays_public(client, calls, monkeypatch):
    monkeypatch.setitem(legacy.app.config, "JWT_SECRET", "")
    assert client.get("/health").status_code == 200


def test_every_route_declares_a_policy():
    for rule in legacy.app.url_map.iter_rules():
        view = legacy.app.view_functions[rule.endpoint]
        assert getattr(view, "billing_policy", None), rule.rule


def test_undeclared_route_fails_closed():
    probe = Flask("probe")
    probe.before_request(auth.enforce_declared_policy)
    probe.add_url_rule("/undeclared", "undeclared", lambda: "open")
    probe.add_url_rule("/declared", "declared", auth.public(lambda: "open"))
    client = probe.test_client()
    assert client.get("/undeclared").status_code == 403
    assert client.get("/declared").status_code == 200


def test_accepts_tokens_minted_by_pyjwt(client, calls):
    jwt = pytest.importorskip("jwt")
    token = jwt.encode(
        {"sub": "user-1", "type": "access", "exp": int(time.time()) + 300, "scope": auth.READ, "tenant_id": TENANT},
        SECRET,
        algorithm="HS256",
    )
    response = client.get(f"/plans/{TENANT}/entitlement", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_no_public_static_route(client, calls):
    assert "static" not in legacy.app.view_functions
    assert client.get("/static/app.js").status_code == 404


def test_method_not_allowed_keeps_allow_header(client, calls):
    response = client.post("/plans", headers=bearer(scope=auth.ADMIN))
    assert response.status_code == 405
    assert set(response.headers["Allow"].split(", ")) >= {"GET", "HEAD"}
    assert response.get_json()["error"] == "Method Not Allowed"


def test_unauthorized_response_is_json_with_bearer_challenge(client, calls):
    response = client.get("/plans")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")
    assert response.get_json()["detail"] == "missing bearer token"


def test_huge_integer_exp_does_not_error(client, calls):
    response = client.get("/api/dunning/overdue", headers=bearer(scope=auth.ADMIN, exp=10**309))
    assert response.status_code == 200
