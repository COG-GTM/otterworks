"""Tests for template API endpoints."""

import uuid

import jwt
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_template(client: AsyncClient, owner_id: uuid.UUID):
    resp = await client.post(
        "/api/v1/templates/",
        json={
            "name": "Meeting Notes",
            "description": "Template for meeting notes",
            "content": "## Meeting Notes\n\n- Attendees:\n- Agenda:",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Meeting Notes"
    assert data["description"] == "Template for meeting notes"
    assert data["created_by"] == str(owner_id)


@pytest.mark.asyncio
async def test_create_template_ignores_body_created_by(
    client: AsyncClient, owner_id: uuid.UUID
):
    victim = uuid.uuid4()
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": "Quarterly report", "content": "planted", "created_by": str(victim)},
    )
    assert resp.status_code == 201
    assert resp.json()["created_by"] == str(owner_id)


@pytest.mark.asyncio
async def test_create_template_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": "Anon", "content": "x"},
        auth=None,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_template_rejects_forged_token(client: AsyncClient):
    forged = jwt.encode({"user_id": str(uuid.uuid4())}, "wrong-secret-padded-to-32-bytes!", "HS256")
    resp = await client.post(
        "/api/v1/templates/",
        json={"name": "Forged", "content": "x"},
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_templates_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/templates/", auth=None)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_templates(client: AsyncClient):
    for name in ["Alpha", "Beta", "Gamma"]:
        await client.post(
            "/api/v1/templates/",
            json={"name": name, "content": f"{name} content"},
        )

    resp = await client.get("/api/v1/templates/")
    assert resp.status_code == 200
    templates = resp.json()
    assert len(templates) == 3
    assert templates[0]["name"] == "Alpha"  # sorted by name


@pytest.mark.asyncio
async def test_create_document_from_template(client: AsyncClient, owner_id: uuid.UUID):
    template_resp = await client.post(
        "/api/v1/templates/",
        json={
            "name": "Blank Doc",
            "content": "Start typing here...",
            "content_type": "text/plain",
        },
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


@pytest.mark.asyncio
async def test_create_from_template_not_found(client: AsyncClient, owner_id: uuid.UUID):
    resp = await client.post(
        f"/api/v1/documents/from-template/{uuid.uuid4()}",
        json={"title": "Orphan", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 404
