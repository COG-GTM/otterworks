"""Tests for comment API endpoints."""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import bearer_auth


async def _create_document(client: AsyncClient, owner_id: uuid.UUID) -> str:
    resp = await client.post(
        "/api/v1/documents/",
        json={"title": "Commented Doc", "content": "", "owner_id": str(owner_id)},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_add_comment(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"content": "Great document!"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Great document!"
    assert data["author_id"] == str(owner_id)
    assert data["document_id"] == doc_id


@pytest.mark.asyncio
async def test_add_comment_ignores_client_supplied_author(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "Spoofed?"},
    )
    assert resp.status_code == 201
    assert resp.json()["author_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_add_comment_document_not_found(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/documents/{uuid.uuid4()}/comments",
        json={"content": "Orphan comment"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_comments(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    for i in range(3):
        await client.post(
            f"/api/v1/documents/{doc_id}/comments",
            json={"content": f"Comment {i}"},
        )

    resp = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_delete_comment(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    comment_resp = await client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"content": "To delete"},
    )
    comment_id = comment_resp.json()["id"]

    resp = await client.delete(f"/api/v1/documents/{doc_id}/comments/{comment_id}")
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/v1/documents/{doc_id}/comments")
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_delete_comment_not_found(client: AsyncClient, owner_id: uuid.UUID):
    doc_id = await _create_document(client, owner_id)

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}/comments/{uuid.uuid4()}"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_comment_routes_require_authentication(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)
    comment_id = (
        await client.post(
            f"/api/v1/documents/{doc_id}/comments", json={"content": "Private"}
        )
    ).json()["id"]

    base = f"/api/v1/documents/{doc_id}/comments"
    assert (await client.get(base, auth=None)).status_code == 401
    assert (
        await client.post(base, json={"content": "anon"}, auth=None)
    ).status_code == 401
    assert (await client.delete(f"{base}/{comment_id}", auth=None)).status_code == 401


@pytest.mark.asyncio
async def test_comment_routes_reject_other_users(
    client: AsyncClient, owner_id: uuid.UUID
):
    doc_id = await _create_document(client, owner_id)
    comment_id = (
        await client.post(
            f"/api/v1/documents/{doc_id}/comments", json={"content": "Private"}
        )
    ).json()["id"]

    attacker = bearer_auth(uuid.uuid4())
    base = f"/api/v1/documents/{doc_id}/comments"

    assert (await client.get(base, auth=attacker)).status_code == 403
    assert (
        await client.post(
            base,
            json={"author_id": str(owner_id), "content": "Forged"},
            auth=attacker,
        )
    ).status_code == 403
    assert (
        await client.delete(f"{base}/{comment_id}", auth=attacker)
    ).status_code == 403

    remaining = (await client.get(base)).json()
    assert [c["id"] for c in remaining] == [comment_id]
    assert remaining[0]["author_id"] == str(owner_id)
