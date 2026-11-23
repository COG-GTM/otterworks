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


def test_refresh_token_is_not_accepted_as_access_token(api_client):
    user = api_client.register_user("refresh-as-access")
    login_data = api_client.login_user(user)
    refresh_headers = {"Authorization": f"Bearer {login_data['refreshToken']}"}

    for route in ("/api/v1/files", "/api/v1/documents", "/api/v1/auth/profile"):
        response = api_client.client.get(route, headers=refresh_headers)
        assert response.status_code == 401, f"{route}: {response.status_code} {response.text}"

    access_headers = {"Authorization": f"Bearer {login_data['accessToken']}"}
    profile = api_client.client.get("/api/v1/auth/profile", headers=access_headers)
    assert profile.status_code == 200, profile.text

    access_on_refresh = api_client.client.post("/api/v1/auth/refresh", headers=access_headers)
    assert access_on_refresh.status_code == 401, access_on_refresh.text

    refreshed = api_client.client.post("/api/v1/auth/refresh", headers=refresh_headers)
    assert refreshed.status_code == 200, refreshed.text
