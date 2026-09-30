import pytest


pytestmark = pytest.mark.api_flow


def test_document_crud_versions_export_comments_and_template_flow(api_client):
    user = api_client.register_user("document-flow")
    headers = user.auth_headers

    create_response = api_client.client.post(
        "/api/v1/documents/",
        headers=headers,
        json={
            "title": f"Flow Document {api_client.run_id}",
            "content": "hello flow world",
        },
    )
    assert create_response.status_code == 201, create_response.text
    document = create_response.json()
    document_id = document["id"]
    assert document["owner_id"] == user.id
    assert document["word_count"] == 3
    assert document["version"] == 1

    get_response = api_client.client.get(f"/api/v1/documents/{document_id}", headers=headers)
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["id"] == document_id

    list_response = api_client.client.get(
        "/api/v1/documents/",
        headers=headers,
        params={"owner_id": user.id, "page": 1, "size": 10},
    )
    assert list_response.status_code == 200, list_response.text
    list_data = list_response.json()
    assert list_data["total"] >= 1
    assert any(item["id"] == document_id for item in list_data["items"])

    put_response = api_client.client.put(
        f"/api/v1/documents/{document_id}",
        headers=headers,
        json={"title": "Updated Flow Document", "content": "updated body text"},
    )
    assert put_response.status_code == 200, put_response.text
    updated = put_response.json()
    assert updated["version"] == 2
    assert updated["word_count"] == 3

    patch_response = api_client.client.patch(
        f"/api/v1/documents/{document_id}",
        headers=headers,
        json={"content": "patched body"},
    )
    assert patch_response.status_code == 200, patch_response.text
    patched = patch_response.json()
    assert patched["version"] == 3
    assert patched["word_count"] == 2

    versions_response = api_client.client.get(
        f"/api/v1/documents/{document_id}/versions",
        headers=headers,
    )
    assert versions_response.status_code == 200, versions_response.text
    versions = versions_response.json()
    assert [version["version_number"] for version in versions] == [1, 2, 3]

    restore_response = api_client.client.post(
        f"/api/v1/documents/{document_id}/versions/{versions[0]['id']}/restore",
        headers=headers,
    )
    assert restore_response.status_code == 200, restore_response.text
    restored = restore_response.json()
    assert restored["content"] == "hello flow world"
    assert restored["version"] == 4

    export_response = api_client.client.get(
        f"/api/v1/documents/{document_id}/export",
        headers=headers,
        params={"format": "markdown"},
    )
    assert export_response.status_code == 200, export_response.text
    assert "hello flow world" in export_response.text

    comment_response = api_client.client.post(
        f"/api/v1/documents/{document_id}/comments",
        headers=headers,
        json={"author_id": user.id, "content": "Looks good"},
    )
    assert comment_response.status_code == 201, comment_response.text
    comment = comment_response.json()
    assert comment["author_id"] == user.id

    comments_response = api_client.client.get(
        f"/api/v1/documents/{document_id}/comments",
        headers=headers,
    )
    assert comments_response.status_code == 200, comments_response.text
    assert any(item["id"] == comment["id"] for item in comments_response.json())

    delete_comment_response = api_client.client.delete(
        f"/api/v1/documents/{document_id}/comments/{comment['id']}",
        headers=headers,
    )
    assert delete_comment_response.status_code == 204, delete_comment_response.text

    template_response = api_client.client.post(
        "/api/v1/templates/",
        headers=headers,
        json={
            "name": f"Flow Template {api_client.run_id}",
            "description": "Template for API flow tests",
            "content": "template body",
            "created_by": user.id,
        },
    )
    assert template_response.status_code == 201, template_response.text
    template = template_response.json()

    from_template_response = api_client.client.post(
        f"/api/v1/documents/from-template/{template['id']}",
        headers=headers,
        json={"title": "From Template", "owner_id": user.id},
    )
    assert from_template_response.status_code == 201, from_template_response.text
    assert from_template_response.json()["content"] == "template body"

    delete_response = api_client.client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert delete_response.status_code == 204, delete_response.text

    deleted_get_response = api_client.client.get(f"/api/v1/documents/{document_id}", headers=headers)
    assert deleted_get_response.status_code == 404


def test_document_validation_and_ownership_risk_cases(api_client):
    user_a = api_client.register_user("document-owner-a")
    user_b = api_client.register_user("document-owner-b")

    missing_owner = api_client.client.post(
        "/api/v1/documents/",
        json={"title": "No owner", "content": "body"},
    )
    assert missing_owner.status_code == 401

    invalid_title = api_client.client.post(
        "/api/v1/documents/",
        headers=user_a.auth_headers,
        json={"title": "", "content": "body"},
    )
    assert invalid_title.status_code in {400, 422}

    create_response = api_client.client.post(
        "/api/v1/documents/",
        headers=user_a.auth_headers,
        json={"title": "Ownership probe", "content": "private body"},
    )
    assert create_response.status_code == 201, create_response.text
    document_id = create_response.json()["id"]

    cross_user_read = api_client.client.get(
        f"/api/v1/documents/{document_id}",
        headers=user_b.auth_headers,
    )
    assert cross_user_read.status_code in {401, 403, 404}

    bad_export_format = api_client.client.get(
        f"/api/v1/documents/{document_id}/export",
        headers=user_a.auth_headers,
        params={"format": "docx"},
    )
    assert bad_export_format.status_code in {400, 422}

    not_found = api_client.client.get(
        "/api/v1/documents/00000000-0000-0000-0000-000000000000",
        headers=user_a.auth_headers,
    )
    assert not_found.status_code == 404


def test_document_trash_restore_and_permanent_delete_flow(api_client):
    user = api_client.register_user("document-trash")
    headers = user.auth_headers
    other_user = api_client.register_user("document-trash-other")

    document = api_client.create_document(
        user, f"Trash Flow {api_client.run_id}", "first draft"
    )
    document_id = document["id"]

    patch_response = api_client.client.patch(
        f"/api/v1/documents/{document_id}",
        headers=headers,
        json={"content": "second draft"},
    )
    assert patch_response.status_code == 200, patch_response.text
    assert patch_response.json()["version"] == 2

    delete_response = api_client.client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert delete_response.status_code == 204, delete_response.text

    gone_response = api_client.client.get(f"/api/v1/documents/{document_id}", headers=headers)
    assert gone_response.status_code == 404, gone_response.text

    trash_response = api_client.client.get("/api/v1/documents/trash", headers=headers)
    api_client.assert_gateway_route_available(trash_response, "/api/v1/documents/trash")
    assert trash_response.status_code == 200, trash_response.text
    trash_data = trash_response.json()
    trashed = next((item for item in trash_data["items"] if item["id"] == document_id), None)
    assert trashed is not None, trash_data
    assert trashed["is_deleted"] is True
    assert trashed["deleted_at"]

    other_trash = api_client.client.get("/api/v1/documents/trash", headers=other_user.auth_headers)
    assert other_trash.status_code == 200, other_trash.text
    assert all(item["id"] != document_id for item in other_trash.json()["items"])

    other_restore = api_client.client.post(
        f"/api/v1/documents/{document_id}/restore", headers=other_user.auth_headers
    )
    assert other_restore.status_code == 403, other_restore.text

    restore_response = api_client.client.post(
        f"/api/v1/documents/{document_id}/restore", headers=headers
    )
    assert restore_response.status_code == 200, restore_response.text
    restored = restore_response.json()
    assert restored["id"] == document_id
    assert restored["is_deleted"] is False
    assert restored["content"] == "second draft"
    assert restored["version"] == 2

    readable_response = api_client.client.get(f"/api/v1/documents/{document_id}", headers=headers)
    assert readable_response.status_code == 200, readable_response.text
    assert readable_response.json()["content"] == "second draft"

    versions_response = api_client.client.get(
        f"/api/v1/documents/{document_id}/versions", headers=headers
    )
    assert versions_response.status_code == 200, versions_response.text
    assert [v["version_number"] for v in versions_response.json()] == [2, 1]

    list_response = api_client.client.get(
        "/api/v1/documents/", headers=headers, params={"owner_id": user.id, "page": 1, "size": 10}
    )
    assert list_response.status_code == 200, list_response.text
    assert any(item["id"] == document_id for item in list_response.json()["items"])

    trash_after_restore = api_client.client.get("/api/v1/documents/trash", headers=headers)
    assert all(item["id"] != document_id for item in trash_after_restore.json()["items"])

    second_restore = api_client.client.post(
        f"/api/v1/documents/{document_id}/restore", headers=headers
    )
    assert second_restore.status_code == 404, second_restore.text

    # A live document cannot be purged directly; it must be trashed first.
    premature_purge = api_client.client.delete(
        f"/api/v1/documents/{document_id}", headers=headers, params={"permanent": "true"}
    )
    assert premature_purge.status_code == 404, premature_purge.text

    delete_again = api_client.client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert delete_again.status_code == 204, delete_again.text

    other_purge = api_client.client.delete(
        f"/api/v1/documents/{document_id}",
        headers=other_user.auth_headers,
        params={"permanent": "true"},
    )
    assert other_purge.status_code == 403, other_purge.text

    purge_response = api_client.client.delete(
        f"/api/v1/documents/{document_id}", headers=headers, params={"permanent": "true"}
    )
    assert purge_response.status_code == 204, purge_response.text

    trash_after_purge = api_client.client.get("/api/v1/documents/trash", headers=headers)
    assert all(item["id"] != document_id for item in trash_after_purge.json()["items"])
    assert (
        api_client.client.get(f"/api/v1/documents/{document_id}", headers=headers).status_code
        == 404
    )
    assert (
        api_client.client.post(
            f"/api/v1/documents/{document_id}/restore", headers=headers
        ).status_code
        == 404
    )
    api_client.created_documents.remove(document_id)
