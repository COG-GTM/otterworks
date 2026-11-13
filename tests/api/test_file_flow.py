import pytest


pytestmark = pytest.mark.api_flow


def test_file_folder_upload_lifecycle_share_and_download(api_client):
    owner = api_client.register_user("file-owner")
    collaborator = api_client.register_user("file-collaborator")

    folder_response = api_client.client.post(
        "/api/v1/folders",
        headers=owner.auth_headers,
        json={"name": f"Flow Folder {api_client.run_id}", "owner_id": owner.id},
    )
    api_client.assert_gateway_route_available(folder_response, "/api/v1/folders")
    assert folder_response.status_code == 201, folder_response.text
    folder = folder_response.json()
    api_client.created_folders.append(folder["id"])

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
            "shared_by": owner.id,
        },
    )
    assert share_response.status_code == 201, share_response.text
    assert share_response.json()["share"]["shared_with"] == collaborator.id

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


def test_folder_stats_breaks_down_nested_files_by_type(api_client):
    owner = api_client.register_user("folder-stats-owner")
    outsider = api_client.register_user("folder-stats-outsider")

    def create_folder(name, parent_id=None):
        response = api_client.client.post(
            "/api/v1/folders",
            headers=owner.auth_headers,
            json={"name": f"{name} {api_client.run_id}", "owner_id": owner.id, "parent_id": parent_id},
        )
        assert response.status_code == 201, response.text
        folder_id = response.json()["id"]
        api_client.created_folders.append(folder_id)
        return folder_id

    def upload(folder_id, name, body, content_type):
        response = api_client.client.post(
            "/api/v1/files/upload",
            headers=owner.auth_headers,
            files={"file": (name, body, content_type)},
            data={"folder_id": folder_id},
        )
        assert response.status_code == 201, response.text
        api_client.created_files.append(response.json()["file"]["id"])

    root_id = create_folder("Stats Root")
    child_id = create_folder("Stats Child", root_id)
    grandchild_id = create_folder("Stats Grandchild", child_id)
    empty_id = create_folder("Stats Empty")

    upload(root_id, "a.txt", b"12345", "text/plain")
    upload(child_id, "b.txt", b"123", "text/plain")
    upload(grandchild_id, "c.csv", b"1,2,3,4", "text/csv")

    stats_response = api_client.client.get(f"/api/v1/folders/{root_id}/stats", headers=owner.auth_headers)
    assert stats_response.status_code == 200, stats_response.text
    stats = stats_response.json()
    assert stats["folder_id"] == root_id
    assert stats["subfolder_count"] == 2
    assert stats["total_files"] == 3
    assert stats["total_size_bytes"] == 15
    by_type = {item["file_type"]: item for item in stats["by_type"]}
    assert by_type["text/plain"]["file_count"] == 2
    assert by_type["text/plain"]["total_size_bytes"] == 8
    assert by_type["text/csv"]["file_count"] == 1
    assert by_type["text/csv"]["total_size_bytes"] == 7

    empty_response = api_client.client.get(f"/api/v1/folders/{empty_id}/stats", headers=owner.auth_headers)
    assert empty_response.status_code == 200, empty_response.text
    assert empty_response.json() == {
        "folder_id": empty_id,
        "subfolder_count": 0,
        "total_files": 0,
        "total_size_bytes": 0,
        "by_type": [],
    }

    forbidden_response = api_client.client.get(f"/api/v1/folders/{root_id}/stats", headers=outsider.auth_headers)
    assert forbidden_response.status_code == 404, forbidden_response.text

    unknown_response = api_client.client.get(
        "/api/v1/folders/00000000-0000-0000-0000-000000000000/stats",
        headers=owner.auth_headers,
    )
    assert unknown_response.status_code == 404, unknown_response.text


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
