"""QA audit of auth-service through the API gateway (see docs/qa/auth-service.md)."""

import uuid

import httpx
import pytest

pytestmark = pytest.mark.api_flow

PASSWORD = "OtterworksTest123!"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(client: httpx.Client, email: str, password: str = PASSWORD, name: str = "QA Auth") -> httpx.Response:
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "displayName": name},
    )


def _login(client: httpx.Client, email: str, password: str) -> httpx.Response:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


# --- registration -----------------------------------------------------------


def test_register_returns_token_pair_and_user_without_password(api_client):
    email = api_client.unique_email("qa-auth-reg")
    resp = _register(api_client.client, email)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["tokenType"] == "Bearer"
    assert data["accessToken"] and data["refreshToken"]
    assert data["expiresIn"] > 0
    assert data["user"]["email"] == email
    assert "password" not in str(data["user"]).lower()
    profile = api_client.client.get("/api/v1/auth/profile", headers=_bearer(data["accessToken"]))
    assert profile.status_code == 200, profile.text
    assert profile.json()["roles"] == ["USER"]


def test_register_duplicate_email_is_rejected(api_client):
    user = api_client.register_user("qa-auth-dup")
    resp = _register(api_client.client, user.email)
    assert resp.status_code == 400, resp.text
    assert "already registered" in resp.json()["message"].lower()


@pytest.mark.xfail(reason="QA-AUTH-02: email uniqueness is case-sensitive", strict=True)
def test_register_duplicate_email_differing_only_in_case_is_rejected(api_client):
    user = api_client.register_user("qa-auth-dupcase")
    resp = _register(api_client.client, user.email.upper())
    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD, "displayName": "X"},
        {"email": "", "password": PASSWORD, "displayName": "X"},
        {"email": "short-pw@example.test", "password": "short", "displayName": "X"},
        {"email": "no-name@example.test", "password": PASSWORD, "displayName": ""},
        {"email": "long-name@example.test", "password": PASSWORD, "displayName": "n" * 101},
        {"password": PASSWORD, "displayName": "X"},
    ],
    ids=["bad-email", "blank-email", "short-password", "blank-name", "long-name", "missing-email"],
)
def test_register_validation_errors_return_400(api_client, payload):
    if payload.get("email", "").endswith("@example.test"):
        payload = {**payload, "email": f"{uuid.uuid4().hex[:8]}-{payload['email']}"}
    resp = api_client.client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 400, resp.text


@pytest.mark.xfail(reason="QA-AUTH-04: malformed JSON is mapped to 500 by the catch-all handler", strict=True)
def test_register_malformed_json_returns_400(api_client):
    resp = api_client.client.post(
        "/api/v1/auth/register",
        content=b'{"email":',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400, resp.text


# --- login ------------------------------------------------------------------


def test_login_success_returns_fresh_tokens(api_client):
    user = api_client.register_user("qa-auth-login")
    data = api_client.login_user(user)
    assert data["accessToken"] and data["refreshToken"]
    assert data["refreshToken"] != user.refresh_token
    assert data["user"]["id"] == user.id


def test_login_bad_password_and_unknown_email_are_indistinguishable(api_client):
    user = api_client.register_user("qa-auth-badpw")
    bad_pw = _login(api_client.client, user.email, "WrongPassword999!")
    unknown = _login(api_client.client, api_client.unique_email("qa-auth-nobody"), "WrongPassword999!")
    assert bad_pw.status_code == unknown.status_code == 400
    assert bad_pw.json()["message"] == unknown.json()["message"] == "Invalid credentials"


def test_login_missing_password_returns_400(api_client):
    resp = api_client.client.post("/api/v1/auth/login", json={"email": "x@example.test"})
    assert resp.status_code == 400, resp.text


@pytest.mark.xfail(reason="QA-AUTH-03: no account lockout or login throttling on repeated failures", strict=True)
def test_login_is_locked_after_repeated_failures(api_client):
    user = api_client.register_user("qa-auth-lockout")
    for _ in range(10):
        assert _login(api_client.client, user.email, "WrongPassword999!").status_code == 400
    resp = _login(api_client.client, user.email, user.password)
    assert resp.status_code in (423, 429), resp.text


# --- tokens -----------------------------------------------------------------


def test_refresh_rotates_and_revokes_previous_refresh_token(api_client):
    user = api_client.register_user("qa-auth-refresh")
    first = api_client.client.post("/api/v1/auth/refresh", headers=_bearer(user.refresh_token))
    assert first.status_code == 200, first.text
    assert first.json()["refreshToken"] != user.refresh_token
    replay = api_client.client.post("/api/v1/auth/refresh", headers=_bearer(user.refresh_token))
    assert replay.status_code == 400, replay.text
    second = api_client.client.post("/api/v1/auth/refresh", headers=_bearer(first.json()["refreshToken"]))
    assert second.status_code == 200, second.text


def test_refresh_rejects_access_token(api_client):
    user = api_client.register_user("qa-auth-refresh-access")
    resp = api_client.client.post("/api/v1/auth/refresh", headers=_bearer(user.access_token))
    assert resp.status_code == 400, resp.text


def test_refresh_token_cannot_be_used_as_access_token(api_client):
    user = api_client.register_user("qa-auth-refresh-as-access")
    resp = api_client.client.get("/api/v1/auth/profile", headers=_bearer(user.refresh_token))
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.parametrize("header", [None, "Bearer not.a.jwt", "Basic Zm9vOmJhcg=="])
def test_protected_routes_reject_missing_or_invalid_tokens(api_client, header):
    headers = {"Authorization": header} if header else {}
    for path in ("/api/v1/auth/profile", "/api/v1/settings"):
        resp = api_client.client.get(path, headers=headers)
        assert resp.status_code == 401, f"{path}: {resp.text}"


def test_logout_revokes_refresh_tokens(api_client):
    user = api_client.register_user("qa-auth-logout")
    out = api_client.client.post("/api/v1/auth/logout", headers=user.auth_headers)
    assert out.status_code == 204, out.text
    resp = api_client.client.post("/api/v1/auth/refresh", headers=_bearer(user.refresh_token))
    assert resp.status_code == 400, resp.text


@pytest.mark.xfail(reason="QA-AUTH-07: logout does not invalidate the access token", strict=True)
def test_logout_invalidates_access_token(api_client):
    user = api_client.register_user("qa-auth-logout-access")
    api_client.client.post("/api/v1/auth/logout", headers=user.auth_headers)
    resp = api_client.client.get("/api/v1/auth/profile", headers=user.auth_headers)
    assert resp.status_code == 401, resp.text


# --- password change --------------------------------------------------------


def test_change_password_requires_current_password_and_rotates_credentials(api_client):
    user = api_client.register_user("qa-auth-chpw")
    wrong = api_client.client.post(
        "/api/v1/auth/change-password",
        headers=user.auth_headers,
        json={"currentPassword": "nope-nope-nope", "newPassword": "BrandNewPass456!"},
    )
    assert wrong.status_code == 400, wrong.text
    ok = api_client.client.post(
        "/api/v1/auth/change-password",
        headers=user.auth_headers,
        json={"currentPassword": user.password, "newPassword": "BrandNewPass456!"},
    )
    assert ok.status_code == 204, ok.text
    assert _login(api_client.client, user.email, user.password).status_code == 400
    assert _login(api_client.client, user.email, "BrandNewPass456!").status_code == 200
    stale = api_client.client.post("/api/v1/auth/refresh", headers=_bearer(user.refresh_token))
    assert stale.status_code == 400, stale.text


def test_change_password_rejects_short_new_password(api_client):
    user = api_client.register_user("qa-auth-chpw-short")
    resp = api_client.client.post(
        "/api/v1/auth/change-password",
        headers=user.auth_headers,
        json={"currentPassword": user.password, "newPassword": "short"},
    )
    assert resp.status_code == 400, resp.text


# --- profile ----------------------------------------------------------------


def test_profile_put_persists_display_name_and_avatar(api_client):
    user = api_client.register_user("qa-auth-profile")
    resp = api_client.client.put(
        "/api/v1/auth/profile",
        headers=user.auth_headers,
        json={"displayName": "QA Renamed", "avatarUrl": "https://example.test/a.png"},
    )
    assert resp.status_code == 200, resp.text
    again = api_client.client.get("/api/v1/auth/profile", headers=user.auth_headers).json()
    assert again["displayName"] == "QA Renamed"
    assert again["avatarUrl"] == "https://example.test/a.png"
    assert again["email"] == user.email


def test_profile_put_rejects_overlong_display_name(api_client):
    user = api_client.register_user("qa-auth-profile-long")
    resp = api_client.client.put("/api/v1/auth/profile", headers=user.auth_headers, json={"displayName": "x" * 101})
    assert resp.status_code == 400, resp.text


@pytest.mark.xfail(reason="QA-AUTH-01: web client sends PATCH /auth/profile, backend only maps PUT (500)", strict=True)
def test_profile_patch_used_by_web_client_is_supported(api_client):
    user = api_client.register_user("qa-auth-profile-patch")
    resp = api_client.client.patch("/api/v1/auth/profile", headers=user.auth_headers, json={"displayName": "Patched"})
    assert resp.status_code == 200, resp.text


def test_profile_is_scoped_to_token_owner(api_client):
    alice = api_client.register_user("qa-auth-alice")
    bob = api_client.register_user("qa-auth-bob")
    api_client.client.put("/api/v1/auth/profile", headers=alice.auth_headers, json={"displayName": "Alice Only"})
    bob_profile = api_client.client.get("/api/v1/auth/profile", headers=bob.auth_headers).json()
    assert bob_profile["id"] == bob.id
    assert bob_profile["displayName"] != "Alice Only"


def test_admin_user_listing_is_forbidden_for_regular_users(api_client):
    user = api_client.register_user("qa-auth-not-admin")
    resp = api_client.client.get("/api/v1/auth/users", headers=user.auth_headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.xfail(reason="QA-AUTH-08: unknown-email lookup returns 400 echoing the email, not 404", strict=True)
def test_lookup_unknown_email_returns_404(api_client):
    user = api_client.register_user("qa-auth-lookup")
    resp = api_client.client.get(
        "/api/v1/auth/users/lookup",
        params={"email": api_client.unique_email("qa-auth-ghost")},
        headers=user.auth_headers,
    )
    assert resp.status_code == 404, resp.text


# --- settings ---------------------------------------------------------------


def test_settings_defaults_for_new_user(api_client):
    user = api_client.register_user("qa-auth-settings-default")
    resp = api_client.client.get("/api/v1/settings", headers=user.auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "notificationEmail": True,
        "notificationInApp": True,
        "notificationDesktop": False,
        "theme": "system",
        "language": "en",
    }


def test_settings_partial_patch_persists_and_keeps_other_fields(api_client):
    user = api_client.register_user("qa-auth-settings-patch")
    resp = api_client.client.patch(
        "/api/v1/settings",
        headers=user.auth_headers,
        json={"notificationEmail": False, "theme": "dark"},
    )
    assert resp.status_code == 200, resp.text
    persisted = api_client.client.get("/api/v1/settings", headers=user.auth_headers).json()
    assert persisted["notificationEmail"] is False
    assert persisted["theme"] == "dark"
    assert persisted["notificationInApp"] is True
    assert persisted["language"] == "en"


def test_settings_are_isolated_per_user(api_client):
    alice = api_client.register_user("qa-auth-settings-a")
    bob = api_client.register_user("qa-auth-settings-b")
    api_client.client.patch("/api/v1/settings", headers=alice.auth_headers, json={"theme": "dark"})
    assert api_client.client.get("/api/v1/settings", headers=bob.auth_headers).json()["theme"] == "system"


@pytest.mark.xfail(reason="QA-AUTH-05: theme longer than VARCHAR(10) is not validated and returns 500", strict=True)
def test_settings_overlong_theme_returns_400(api_client):
    user = api_client.register_user("qa-auth-settings-long")
    resp = api_client.client.patch("/api/v1/settings", headers=user.auth_headers, json={"theme": "midnight-blue-hc"})
    assert resp.status_code == 400, resp.text


@pytest.mark.xfail(reason="QA-AUTH-05: theme/language accept arbitrary values (no allow-list)", strict=True)
def test_settings_unknown_theme_value_is_rejected(api_client):
    user = api_client.register_user("qa-auth-settings-enum")
    resp = api_client.client.patch("/api/v1/settings", headers=user.auth_headers, json={"theme": "neon"})
    assert resp.status_code == 400, resp.text
