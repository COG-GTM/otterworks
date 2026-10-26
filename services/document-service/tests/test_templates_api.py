"""Tests for template API endpoints."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import bearer_auth, sign_token


@pytest.mark.asyncio
async def test_create_template(client: AsyncClient, admin_auth, admin_id: uuid.UUID):
    resp = await client.post(
        "/api/v1/templates/",
        json={
            "name": "Meeting Notes",
            "description": "Template for meeting notes",
            "content": "## Meeting Notes\n\n- Attendees:\n- Agenda:",
        },
        auth=admin_auth,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Meeting Notes"
    assert data["description"] == "Template for meeting notes"
    assert data["created_by"] == str(admin_id)


@pytest.mark.asyncio
async def test_list_templates(client: AsyncClient, admin_auth):
    for name in ["Alpha", "Beta", "Gamma"]:
        await client.post(
            "/api/v1/templates/",
            json={"name": name, "content": f"{name} content"},
            auth=admin_auth,
        )

    # Any signed-in user (the default client is a plain user) sees the templates.
    resp = await client.get("/api/v1/templates/")
    assert resp.status_code == 200
    templates = resp.json()
    assert len(templates) == 3
    assert templates[0]["name"] == "Alpha"  # sorted by name


@pytest.mark.asyncio
async def test_create_document_from_template(
    client: AsyncClient, admin_auth, owner_id: uuid.UUID
):
    template_resp = await client.post(
        "/api/v1/templates/",
        json={
            "name": "Blank Doc",
            "content": "Start typing here...",
            "content_type": "text/plain",
        },
        auth=admin_auth,
    )
    template_id = template_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/documents/from-template/{template_id}",
        json={"title": "My New Doc", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "My New Doc"
    assert data["content"] == "Start typing here..."
    assert data["content_type"] == "text/plain"
    assert data["owner_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_create_from_template_not_found(client: AsyncClient, owner_id: uuid.UUID):
    resp = await client.post(
        f"/api/v1/documents/from-template/{uuid.uuid4()}",
        json={"title": "Orphan", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_template_stores_caller_not_body_created_by(
    client: AsyncClient, admin_auth, admin_id: uuid.UUID
):
    victim = uuid.uuid4()
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": "Quarterly report", "content": "planted", "created_by": str(victim)},
        auth=admin_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["created_by"] == str(admin_id)

    listed = (await client.get("/api/v1/templates/")).json()
    assert [t["created_by"] for t in listed] == [str(admin_id)]


@pytest.mark.asyncio
async def test_create_template_requires_authentication(client: AsyncClient):
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": "Anon", "content": "x", "created_by": str(uuid.uuid4())},
        auth=None,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("roles", [None, ["USER"], ["EDITOR"], "USER"])
async def test_create_template_rejects_non_admin(client: AsyncClient, roles):
    claims = {} if roles is None else {"roles": roles}
    victim = uuid.uuid4()
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": "Quarterly report", "content": "planted", "created_by": str(victim)},
        auth=bearer_auth(uuid.uuid4(), **claims),
    )
    assert resp.status_code == 403
    assert (await client.get("/api/v1/templates/")).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "OWNER", "admin"])
async def test_create_template_accepts_admin_roles(client: AsyncClient, role):
    author = uuid.uuid4()
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": f"By {role}"},
        auth=bearer_auth(author, roles=[role]),
    )
    assert resp.status_code == 201
    assert resp.json()["created_by"] == str(author)


@pytest.mark.asyncio
async def test_create_template_rejects_admin_refresh_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": "Refresh"},
        auth=bearer_auth(uuid.uuid4(), roles=["ADMIN"], type="refresh"),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_template_ignores_unsigned_admin_claims(client: AsyncClient):
    import jwt

    forged = jwt.encode(
        {"user_id": str(uuid.uuid4()), "roles": ["ADMIN"]}, "wrong-secret-" * 3, algorithm="HS256"
    )
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": "Forged"},
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_templates_requires_authentication(client: AsyncClient):
    resp = await client.get("/api/v1/templates/", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_from_template_requires_authentication(
    client: AsyncClient, admin_auth, owner_id: uuid.UUID
):
    template_id = (
        await client.post("/api/v1/templates/", json={"name": "T"}, auth=admin_auth)
    ).json()["id"]
    resp = await client.post(
        f"/api/v1/documents/from-template/{template_id}",
        json={"title": "Anon", "owner_id": str(owner_id)},
        auth=None,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_from_template_rejects_foreign_owner(
    client: AsyncClient, admin_auth
):
    template_id = (
        await client.post("/api/v1/templates/", json={"name": "T"}, auth=admin_auth)
    ).json()["id"]
    resp = await client.post(
        f"/api/v1/documents/from-template/{template_id}",
        json={"title": "Planted", "owner_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_from_template_defaults_owner_to_caller(
    client: AsyncClient, admin_auth, owner_id: uuid.UUID
):
    template_id = (
        await client.post(
            "/api/v1/templates/", json={"name": "T", "content": "body"}, auth=admin_auth
        )
    ).json()["id"]
    resp = await client.post(
        f"/api/v1/documents/from-template/{template_id}",
        json={"title": "Mine"},
        headers={"Authorization": f"Bearer {sign_token(owner_id)}"},
    )
    assert resp.status_code == 201
    assert resp.json()["owner_id"] == str(owner_id)
