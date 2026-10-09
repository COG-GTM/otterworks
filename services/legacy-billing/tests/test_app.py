import pytest

import app as legacy

GUARD = {legacy.REQUEST_HEADER: "1"}


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def fake_execute(sql, params=()):
        recorded.append((sql, params))

    def fake_select(sql, params=()):
        recorded.append((sql, params))
        return [{"ok": True}]

    monkeypatch.setattr(legacy, "execute", fake_execute)
    monkeypatch.setattr(legacy, "select", fake_select)
    return recorded


@pytest.fixture
def make_client(monkeypatch):
    def build(**env):
        for name in ("LEGACY_BILLING_API_TOKEN", "LEGACY_BILLING_ALLOWED_HOSTS"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setitem(legacy.app.config, "TRUSTED_HOSTS", legacy.allowed_hosts())
        monkeypatch.setitem(legacy.app.config, "API_TOKEN", env.get("LEGACY_BILLING_API_TOKEN", ""))
        return legacy.app.test_client()

    return build


@pytest.fixture
def client(make_client):
    return make_client()


FORM_POSTS = [
    ("/plans/t-1/change", {"plan_id": "p-2", "effective_on": "2026-02-01"}),
    ("/api/invoices/t-1/issue", {"period_start": "2026-02-01", "period_end": "2026-02-28"}),
    ("/api/dunning/schedule", {"as_of": "2026-02-28"}),
    ("/api/dunning/suspend", {"as_of": "2026-02-28"}),
]
JSON_POSTS = ["/api/rating/preview", "/api/rating/finalize"]
RATING = {"tenant_id": "t-1", "period_start": "2026-02-01", "period_end": "2026-02-28"}


@pytest.mark.parametrize(("path", "form"), FORM_POSTS)
def test_form_post_without_request_header_is_rejected(client, calls, path, form):
    assert client.post(path, data=form).status_code == 403
    assert calls == []


@pytest.mark.parametrize(("path", "form"), FORM_POSTS)
def test_form_post_with_request_header_runs_procedure(client, calls, path, form):
    response = client.post(path, data=form, headers=GUARD)
    assert response.status_code in (200, 302)
    assert len(calls) == 1


@pytest.mark.parametrize("path", JSON_POSTS)
def test_cross_site_text_plain_json_is_rejected(client, calls, path):
    response = client.post(
        path,
        data='{"tenant_id": "t-1", "period_start": "2026-02-01", "period_end": "2026-02-28"}',
        content_type="text/plain",
        headers=GUARD,
    )
    assert response.status_code == 415
    assert calls == []


@pytest.mark.parametrize("path", JSON_POSTS)
def test_json_post_with_request_header_runs_procedure(client, calls, path):
    assert client.post(path, json=RATING, headers=GUARD).status_code == 200
    assert calls[0][1] == ("t-1", "2026-02-01", "2026-02-28")


@pytest.mark.parametrize("path", JSON_POSTS)
def test_json_post_without_request_header_is_rejected(client, calls, path):
    assert client.post(path, json=RATING).status_code == 403
    assert calls == []


def test_foreign_origin_is_rejected(client, calls):
    headers = {**GUARD, "Origin": "https://attacker.example"}
    response = client.post("/api/dunning/suspend", data={"as_of": "2026-02-28"}, headers=headers)
    assert response.status_code == 403
    assert calls == []


def test_cross_site_fetch_metadata_is_rejected(client, calls):
    headers = {**GUARD, "Sec-Fetch-Site": "cross-site"}
    response = client.post("/api/dunning/suspend", data={"as_of": "2026-02-28"}, headers=headers)
    assert response.status_code == 403
    assert calls == []


def test_same_origin_post_is_allowed(client, calls):
    headers = {**GUARD, "Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}
    response = client.post("/api/dunning/suspend", data={"as_of": "2026-02-28"}, headers=headers)
    assert response.status_code == 200
    assert calls == [("CALL billing.sp_suspend_overdue(%s)", ("2026-02-28",))]


def test_reads_do_not_need_request_header(client, calls):
    assert client.get("/api/dunning/overdue").status_code == 200
    assert client.get("/plans/t-1/entitlement").status_code == 200


@pytest.mark.parametrize("host", ["localhost:8096", "127.0.0.1:8096", "legacy-billing:8096"])
def test_local_hosts_are_trusted(client, calls, host):
    assert client.get("/api/dunning/overdue", headers={"Host": host}).status_code == 200


def test_rebound_host_is_rejected(client, calls):
    response = client.get("/api/dunning/overdue", headers={"Host": "attacker.example:8096"})
    assert response.status_code == 400
    assert calls == []


def test_allowed_hosts_can_be_configured(make_client, calls):
    client = make_client(LEGACY_BILLING_ALLOWED_HOSTS="billing.internal")
    assert client.get("/plans", headers={"Host": "billing.internal"}).status_code == 200
    assert client.get("/plans", headers={"Host": "localhost"}).status_code == 400


def test_api_token_is_required_when_configured(make_client, calls):
    client = make_client(LEGACY_BILLING_API_TOKEN="s3cret")
    assert client.get("/api/dunning/overdue").status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert client.get("/api/dunning/overdue", headers=wrong).status_code == 401
    ok = {"Authorization": "Bearer s3cret"}
    assert client.get("/api/dunning/overdue", headers=ok).status_code == 200
    form = {"as_of": "2026-02-28"}
    response = client.post("/api/dunning/schedule", data=form, headers=wrong | GUARD)
    assert response.status_code == 401
    response = client.post("/api/dunning/schedule", data=form, headers=ok | GUARD)
    assert response.status_code == 200
    assert len(calls) == 2


def test_health_stays_public_when_token_configured(make_client, calls):
    client = make_client(LEGACY_BILLING_API_TOKEN="s3cret")
    assert client.get("/health").status_code == 200
