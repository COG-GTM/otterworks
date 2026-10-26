import pytest


pytestmark = pytest.mark.api_flow


def test_file_folder_upload_lifecycle_share_and_download(api_client):
    owner = api_client.register_user("file-owner")
    collaborator = api_client.register_user("file-collaborator")

    folder_response = api_client.client.post(
        "/api/v1/folders",
        headers=owner.auth_headers,
        json={"name": f"Flow Folder {api_client.run_id}"},
    )
    api_client.assert_gateway_route_available(folder_response, "/api/v1/folders")
    assert folder_response.status_code == 201, folder_response.text
    folder = folder_response.json()
    api_client.created_folders.append(folder["id"])
    assert folder["owner_id"] == owner.id

    upload_response = api_client.client.post(
        "/api/v1/files/upload",
        headers=owner.auth_headers,
        files={"file": ("flow.txt", b"hello file flow", "text/plain")},
        data={"folder_id": folder["id"]},
    )
    assert upload_response.status_code == 201, upload_response.text
    file_metadata = upload_response.json()["file"]
    file_id = file_metadata["id"]
    api_client.created_files.append(file_id)
    assert file_metadata["owner_id"] == owner.id
    assert file_metadata["folder_id"] == folder["id"]
    assert file_metadata["version"] == 1

    list_response = api_client.client.get(
        "/api/v1/files",
        headers=owner.auth_headers,
        params={"owner_id": owner.id, "page": 1, "page_size": 10},
    )
    assert list_response.status_code == 200, list_response.text
    assert any(item["id"] == file_id for item in list_response.json()["files"])

    get_response = api_client.client.get(f"/api/v1/files/{file_id}", headers=owner.auth_headers)
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["id"] == file_id

    download_response = api_client.client.get(
        f"/api/v1/files/{file_id}/download",
        headers=owner.auth_headers,
    )
    assert download_response.status_code == 200, download_response.text
    assert download_response.json()["url"]

    versions_response = api_client.client.get(
        f"/api/v1/files/{file_id}/versions",
        headers=owner.auth_headers,
    )
    assert versions_response.status_code == 200, versions_response.text
    assert versions_response.json()["versions"][0]["version"] == 1

    share_response = api_client.client.post(
        f"/api/v1/files/{file_id}/share",
        headers=owner.auth_headers,
        json={
            "shared_with": collaborator.id,
            "permission": "viewer",
        },
    )
    assert share_response.status_code == 201, share_response.text
    assert share_response.json()["share"]["shared_with"] == collaborator.id
    assert share_response.json()["share"]["shared_by"] == owner.id

    trash_response = api_client.client.post(f"/api/v1/files/{file_id}/trash", headers=owner.auth_headers)
    assert trash_response.status_code == 200, trash_response.text
    assert trash_response.json()["is_trashed"] is True

    restore_response = api_client.client.post(f"/api/v1/files/{file_id}/restore", headers=owner.auth_headers)
    assert restore_response.status_code == 200, restore_response.text
    assert restore_response.json()["is_trashed"] is False

    move_response = api_client.client.put(
        f"/api/v1/files/{file_id}/move",
        headers=owner.auth_headers,
        json={"folder_id": None},
    )
    assert move_response.status_code == 200, move_response.text
    assert move_response.json()["folder_id"] is None

    delete_file_response = api_client.client.delete(f"/api/v1/files/{file_id}", headers=owner.auth_headers)
    assert delete_file_response.status_code == 204, delete_file_response.text
    api_client.created_files.remove(file_id)

    deleted_get_response = api_client.client.get(f"/api/v1/files/{file_id}", headers=owner.auth_headers)
    assert deleted_get_response.status_code == 404

    delete_folder_response = api_client.client.delete(
        f"/api/v1/folders/{folder['id']}",
        headers=owner.auth_headers,
    )
    assert delete_folder_response.status_code == 204, delete_folder_response.text
    api_client.created_folders.remove(folder["id"])


@pytest.mark.gap_revealer
def test_file_validation_and_route_gaps(api_client):
    owner = api_client.register_user("file-validation")

    empty_upload_response = api_client.client.post(
        "/api/v1/files/upload",
        headers=owner.auth_headers,
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert empty_upload_response.status_code in {400, 422}

    missing_owner_upload = api_client.client.post(
        "/api/v1/files/upload",
        files={"file": ("no-owner.txt", b"body", "text/plain")},
    )
    assert missing_owner_upload.status_code in {400, 401, 403}

    invalid_file_id = api_client.client.get("/api/v1/files/not-a-uuid", headers=owner.auth_headers)
    assert invalid_file_id.status_code in {400, 422}

    folder_route_response = api_client.client.post(
        "/api/v1/folders",
        headers=owner.auth_headers,
        json={"name": "route probe", "owner_id": owner.id},
    )
    api_client.assert_gateway_route_available(folder_route_response, "/api/v1/folders")


def test_folder_owner_and_share_actor_come_from_the_authenticated_caller(api_client):
    victim = api_client.register_user("actor-victim")
    attacker = api_client.register_user("actor-attacker")
    recipient = api_client.register_user("actor-recipient")

    spoofed_folder = api_client.client.post(
        "/api/v1/folders",
        headers=attacker.auth_headers,
        json={"name": f"Payroll {api_client.run_id}", "owner_id": victim.id},
    )
    api_client.assert_gateway_route_available(spoofed_folder, "/api/v1/folders")
    if spoofed_folder.status_code == 201:
        api_client.created_folders.append(spoofed_folder.json()["id"])
    assert spoofed_folder.status_code == 403, spoofed_folder.text

    victim_folder_response = api_client.client.post(
        "/api/v1/folders",
        headers=victim.auth_headers,
        json={"name": f"Victim Root {api_client.run_id}"},
    )
    assert victim_folder_response.status_code == 201, victim_folder_response.text
    victim_folder = victim_folder_response.json()
    api_client.created_folders.append(victim_folder["id"])
    assert victim_folder["owner_id"] == victim.id

    nested_in_victim_tree = api_client.client.post(
        "/api/v1/folders",
        headers=attacker.auth_headers,
        json={"name": f"Payroll {api_client.run_id}", "parent_id": victim_folder["id"]},
    )
    if nested_in_victim_tree.status_code == 201:
        api_client.created_folders.append(nested_in_victim_tree.json()["id"])
    assert nested_in_victim_tree.status_code == 403, nested_in_victim_tree.text

    victim_children = api_client.client.get(
        "/api/v1/folders",
        headers=victim.auth_headers,
        params={"parent_id": victim_folder["id"]},
    )
    assert victim_children.status_code == 200, victim_children.text
    assert victim_children.json()["folders"] == []

    upload_response = api_client.client.post(
        "/api/v1/files/upload",
        headers=attacker.auth_headers,
        files={"file": ("actor.txt", b"actor attribution", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    file_id = upload_response.json()["file"]["id"]
    api_client.created_files.append(file_id)

    spoofed_share = api_client.client.post(
        f"/api/v1/files/{file_id}/share",
        headers=attacker.auth_headers,
        json={"shared_with": recipient.id, "permission": "editor", "shared_by": victim.id},
    )
    assert spoofed_share.status_code == 403, spoofed_share.text

    share_response = api_client.client.post(
        f"/api/v1/files/{file_id}/share",
        headers=attacker.auth_headers,
        json={"shared_with": recipient.id, "permission": "editor"},
    )
    assert share_response.status_code == 201, share_response.text
    assert share_response.json()["share"]["shared_by"] == attacker.id

    victim_activity = api_client.client.get("/api/v1/activity", headers=victim.auth_headers)
    if victim_activity.status_code == 200:
        assert all(item["resource_id"] != file_id for item in victim_activity.json()["items"])
