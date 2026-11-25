"""DV-8: GET /documents must only list the authenticated caller's documents."""

import uuid

import jwt
import pytest
from httpx import AsyncClient

from tests.conftest import TEST_JWT_SECRET

LIST_PATHS = ["/api/v1/documents/", "/api/v1/documents"]


async def _create(client: AsyncClient, user_id: uuid.UUID, title: str) -> None:
    token = jwt.encode({"sub": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256")
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": title, "content": f"{title} private content"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201


@pytest.fixture
async def two_users(client: AsyncClient) -> tuple[uuid.UUID, uuid.UUID]:
    alice, bob = uuid.uuid4(), uuid.uuid4()
    await _create(client, alice, "ALICE-PRIVATE")
    await _create(client, bob, "BOB-NOTE")
    return alice, bob


def _bearer(user_id: uuid.UUID, algorithm: str) -> dict[str, str]:
    token = jwt.encode({"sub": str(user_id)}, TEST_JWT_SECRET, algorithm=algorithm)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LIST_PATHS)
@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
async def test_list_returns_only_callers_documents(client, two_users, path, algorithm):
    _, bob = two_users
    resp = await client.get(path, headers=_bearer(bob, algorithm))
    assert resp.status_code == 200
    assert [d["title"] for d in resp.json()["items"]] == ["BOB-NOTE"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LIST_PATHS)
async def test_filtered_list_returns_only_callers_documents(client, two_users, path):
    _, bob = two_users
    resp = await client.get(
        path, params={"sort": "title", "direction": "asc"}, headers=_bearer(bob, "HS512")
    )
    assert resp.status_code == 200
    assert [d["title"] for d in resp.json()["items"]] == ["BOB-NOTE"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LIST_PATHS)
async def test_owner_id_of_another_user_is_forbidden(client, two_users, path):
    alice, bob = two_users
    resp = await client.get(path, params={"owner_id": str(alice)}, headers=_bearer(bob, "HS256"))
    assert resp.status_code == 403
    assert "ALICE-PRIVATE" not in resp.text


@pytest.mark.asyncio
async def test_owner_id_matching_caller_is_allowed(client, two_users):
    _, bob = two_users
    resp = await client.get(
        "/api/v1/documents/", params={"owner_id": str(bob)}, headers=_bearer(bob, "HS256")
    )
    assert resp.status_code == 200
    assert [d["title"] for d in resp.json()["items"]] == ["BOB-NOTE"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LIST_PATHS)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {
            "Authorization": "Bearer "
            + jwt.encode(
                {"sub": str(uuid.uuid4())}, "wrong-secret-wrong-secret-pad32", algorithm="HS512"
            )
        },
    ],
    ids=["no-token", "garbage-token", "wrong-secret"],
)
async def test_unauthenticated_list_is_401_not_unfiltered(client, two_users, path, headers):
    resp = await client.get(path, headers=headers, auth=None)
    assert resp.status_code == 401
    assert "PRIVATE" not in resp.text


@pytest.mark.asyncio
async def test_refresh_token_is_not_accepted_as_access_token(client, two_users):
    _, bob = two_users
    token = jwt.encode({"sub": str(bob), "type": "refresh"}, TEST_JWT_SECRET, algorithm="HS512")
    resp = await client.get("/api/v1/documents/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
