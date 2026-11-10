import pytest

pytestmark = pytest.mark.api_flow


def test_folder_share_link_create_open_and_revoke_flow(api_client):
    """OTW-29: owner shares a folder; recipient opens it without a JWT; revoke -> 410."""
    owner = api_client.register_user("folder-share-owner")
    stranger = api_client.register_user("folder-share-stranger")

    folder_response = api_client.client.post(
        "/api/v1/folders",
        headers=owner.auth_headers,
        json={"name": f"Shared Folder {api_client.run_id}", "owner_id": owner.id},
    )
    assert folder_response.status_code == 201, folder_response.text
    folder_id = folder_response.json()["id"]
    api_client.created_folders.append(folder_id)

    doc_response = api_client.client.post(
        "/api/v1/documents/",
        headers=owner.auth_headers,
        json={"title": f"Shared Doc {api_client.run_id}", "content": "shared body",
              "folder_id": folder_id},
    )
    assert doc_response.status_code == 201, doc_response.text
    document = doc_response.json()
    api_client.created_documents.append(document["id"])
    outside = api_client.create_document(owner, f"Outside {api_client.run_id}", "private")

    links_path = f"/api/v1/documents/folders/{folder_id}/share-links"
    assert api_client.client.post(links_path, headers=stranger.auth_headers).status_code == 403
    assert api_client.client.post(links_path).status_code == 401

    create_response = api_client.client.post(links_path, headers=owner.auth_headers, json={})
    assert create_response.status_code == 201, create_response.text
    link = create_response.json()
    assert link["status"] == "active"
    assert link["expires_at"]
    assert link["url"].endswith(f"/shared-folder/{link['token']}")

    # Recipient: no Authorization header at all.
    shared_path = f"/api/v1/documents/shared-folders/{link['token']}"
    open_response = api_client.client.get(shared_path)
    assert open_response.status_code == 200, open_response.text
    assert [d["id"] for d in open_response.json()["documents"]] == [document["id"]]
    read_response = api_client.client.get(f"{shared_path}/documents/{document['id']}")
    assert read_response.status_code == 200, read_response.text
    assert read_response.json()["content"] == "shared body"
    assert api_client.client.get(f"{shared_path}/documents/{outside['id']}").status_code == 404
    assert api_client.client.get(
        "/api/v1/documents/shared-folders/not-a-real-token").status_code == 404

    list_response = api_client.client.get(links_path, headers=owner.auth_headers)
    assert list_response.status_code == 200, list_response.text
    assert [i["status"] for i in list_response.json()["items"]] == ["active"]

    revoke_response = api_client.client.delete(
        f"/api/v1/documents/share-links/{link['id']}", headers=owner.auth_headers)
    assert revoke_response.status_code == 204, revoke_response.text

    gone = api_client.client.get(shared_path)
    assert gone.status_code == 410
    assert gone.json()["detail"] == "Share link revoked"
    assert api_client.client.get(f"{shared_path}/documents/{document['id']}").status_code == 410
    patch_response = api_client.client.patch(
        f"/api/v1/documents/share-links/{link['id']}",
        headers=owner.auth_headers, json={"expires_in_seconds": 7200})
    assert patch_response.status_code == 409
