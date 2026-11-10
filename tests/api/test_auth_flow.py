import os

import pytest


pytestmark = pytest.mark.api_flow


def test_register_login_profile_refresh_and_logout(api_client):
    user = api_client.register_user("auth-flow")

    login_data = api_client.login_user(user)
    assert login_data["tokenType"] == "Bearer"
    assert login_data["accessToken"]
    assert login_data["refreshToken"]
    assert login_data["user"]["email"] == user.email

    profile_response = api_client.client.get(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {login_data['accessToken']}"},
    )
    assert profile_response.status_code == 200, profile_response.text
    assert profile_response.json()["email"] == user.email

    update_response = api_client.client.put(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {login_data['accessToken']}"},
        json={"displayName": "API Flow Updated User"},
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["displayName"] == "API Flow Updated User"

    refresh_response = api_client.client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {login_data['refreshToken']}"},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    refreshed = refresh_response.json()
    assert refreshed["accessToken"]
    assert refreshed["refreshToken"]
    assert refreshed["refreshToken"] != login_data["refreshToken"]

    reused_refresh_response = api_client.client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {login_data['refreshToken']}"},
    )
    assert reused_refresh_response.status_code in {400, 401, 403}

    logout_response = api_client.client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {refreshed['accessToken']}"},
    )
    assert logout_response.status_code == 204, logout_response.text


def test_auth_validation_and_protected_routes(api_client):
    invalid_register = api_client.client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "short", "displayName": ""},
    )
    assert invalid_register.status_code == 400

    user = api_client.register_user("duplicate-auth-flow")
    duplicate = api_client.client.post(
        "/api/v1/auth/register",
        json={
            "email": user.email,
            "password": user.password,
            "displayName": user.display_name,
        },
    )
    assert duplicate.status_code in {400, 409}

    invalid_login = api_client.client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong-password"},
    )
    assert invalid_login.status_code in {400, 401}

    unauthenticated_profile = api_client.client.get("/api/v1/auth/profile")
    assert unauthenticated_profile.status_code in {401, 403}

    non_admin_users = api_client.client.get("/api/v1/auth/users", headers=user.auth_headers)
    assert non_admin_users.status_code in {401, 403}


LOCKOUT_MAX_ATTEMPTS = int(os.getenv("OTTERWORKS_AUTH_LOCKOUT_MAX_ATTEMPTS", "5"))


def test_account_locks_after_repeated_failed_logins(api_client):
    user = api_client.register_user("lockout-flow")

    for _ in range(LOCKOUT_MAX_ATTEMPTS):
        failed = api_client.client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong-password"},
        )
        assert failed.status_code in {400, 401}, failed.text

    locked = api_client.client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": user.password},
    )
    assert locked.status_code == 423, locked.text
    body = api_client.assert_json_error(locked)
    assert body["message"] == "Account temporarily locked, try again later"


def test_successful_login_resets_failed_attempt_counter(api_client):
    user = api_client.register_user("lockout-reset-flow")

    for _ in range(LOCKOUT_MAX_ATTEMPTS - 1):
        failed = api_client.client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong-password"},
        )
        assert failed.status_code in {400, 401}, failed.text

    api_client.login_user(user)

    for _ in range(LOCKOUT_MAX_ATTEMPTS - 1):
        failed = api_client.client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong-password"},
        )
        assert failed.status_code in {400, 401}, failed.text

    api_client.login_user(user)


def test_unknown_email_is_never_locked(api_client):
    email = api_client.unique_email("lockout-unknown")

    for _ in range(LOCKOUT_MAX_ATTEMPTS + 2):
        response = api_client.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        assert response.status_code in {400, 401}, response.text
        assert response.json()["message"] == "Invalid credentials"
