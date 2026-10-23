import pytest


pytestmark = pytest.mark.api_flow


def test_register_login_profile_refresh_and_logout(api_client):
    user = api_client.register_user("auth-flow")

    login_response = api_client.client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": user.password},
    )
    assert login_response.status_code == 200, login_response.text
    login_data = login_response.json()
    assert login_data["tokenType"] == "Bearer"
    assert login_data["accessToken"]
    # The refresh token is only delivered as an HttpOnly cookie scoped to the auth endpoints.
    assert "refreshToken" not in login_data
    set_cookie = login_response.headers["set-cookie"]
    for attribute in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/api/v1/auth"):
        assert attribute in set_cookie
    refresh_token = login_response.cookies["otter_refresh_token"]

    replayed_as_bearer = api_client.client.get(
        "/api/v1/documents/", headers={"Authorization": f"Bearer {refresh_token}"}
    )
    assert replayed_as_bearer.status_code == 401, replayed_as_bearer.text
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
        headers={"Cookie": f"otter_refresh_token={refresh_token}"},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    refreshed = refresh_response.json()
    assert refreshed["accessToken"]
    assert "refreshToken" not in refreshed
    rotated_refresh_token = refresh_response.cookies["otter_refresh_token"]
    assert rotated_refresh_token != refresh_token

    reused_refresh_response = api_client.client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"otter_refresh_token={refresh_token}"},
    )
    assert reused_refresh_response.status_code in {400, 401, 403}

    bearer_refresh_response = api_client.client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {rotated_refresh_token}"},
    )
    assert bearer_refresh_response.status_code == 401

    logout_response = api_client.client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {refreshed['accessToken']}"},
    )
    assert logout_response.status_code == 204, logout_response.text
    assert "Max-Age=0" in logout_response.headers["set-cookie"]

    after_logout = api_client.client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"otter_refresh_token={rotated_refresh_token}"},
    )
    assert after_logout.status_code in {400, 401, 403}


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
