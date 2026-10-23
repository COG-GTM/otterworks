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


def test_file_and_folder_endpoints_enforce_ownership(api_client):
    owner = api_client.register_user("file-idor-owner")
    attacker = api_client.register_user("file-idor-attacker")
    viewer = api_client.register_user("file-idor-viewer")

    folder_response = api_client.client.post(
        "/api/v1/folders",
        headers=owner.auth_headers,
        json={"name": f"Private {api_client.run_id}"},
    )
    assert folder_response.status_code == 201, folder_response.text
    folder = folder_response.json()
    api_client.created_folders.append(folder["id"])
    assert folder["owner_id"] == owner.id

    forged_folder = api_client.client.post(
        "/api/v1/folders",
        headers=attacker.auth_headers,
        json={"name": "planted", "owner_id": owner.id},
    )
    assert forged_folder.status_code == 403, forged_folder.text

    upload_response = api_client.client.post(
        "/api/v1/files/upload",
        headers=owner.auth_headers,
        files={"file": ("secret.txt", b"owner only", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    file_id = upload_response.json()["file"]["id"]
    api_client.created_files.append(file_id)

    attacker_requests = [
        ("GET", f"/api/v1/files/{file_id}", None),
        ("GET", f"/api/v1/files/{file_id}/download", None),
        ("GET", f"/api/v1/files/{file_id}/versions", None),
        ("PATCH", f"/api/v1/files/{file_id}/rename", {"name": "pwned.txt"}),
        ("PUT", f"/api/v1/files/{file_id}/move", {"folder_id": None}),
        ("POST", f"/api/v1/files/{file_id}/trash", None),
        ("POST", f"/api/v1/files/{file_id}/restore", None),
        (
            "POST",
            f"/api/v1/files/{file_id}/share",
            {"shared_with": attacker.id, "permission": "editor", "shared_by": owner.id},
        ),
        ("DELETE", f"/api/v1/files/{file_id}", None),
        ("GET", f"/api/v1/folders/{folder['id']}", None),
        ("PUT", f"/api/v1/folders/{folder['id']}", {"name": "pwned"}),
        ("DELETE", f"/api/v1/folders/{folder['id']}", None),
    ]
    for method, path, body in attacker_requests:
        response = api_client.client.request(method, path, headers=attacker.auth_headers, json=body)
        assert response.status_code == 404, f"{method} {path}: {response.status_code} {response.text}"

    attacker_shared = api_client.client.get("/api/v1/files/shared", headers=attacker.auth_headers)
    assert attacker_shared.status_code == 200, attacker_shared.text
    assert all(item["id"] != file_id for item in attacker_shared.json()["files"])

    share_response = api_client.client.post(
        f"/api/v1/files/{file_id}/share",
        headers=owner.auth_headers,
        json={"shared_with": viewer.id, "permission": "viewer", "shared_by": attacker.id},
    )
    assert share_response.status_code == 201, share_response.text
    assert share_response.json()["share"]["shared_by"] == owner.id

    viewer_download = api_client.client.get(
        f"/api/v1/files/{file_id}/download", headers=viewer.auth_headers
    )
    assert viewer_download.status_code == 200, viewer_download.text
    viewer_reshare = api_client.client.post(
        f"/api/v1/files/{file_id}/share",
        headers=viewer.auth_headers,
        json={"shared_with": attacker.id, "permission": "viewer"},
    )
    assert viewer_reshare.status_code == 403, viewer_reshare.text
    viewer_rename = api_client.client.patch(
        f"/api/v1/files/{file_id}/rename", headers=viewer.auth_headers, json={"name": "x.txt"}
    )
    assert viewer_rename.status_code == 403, viewer_rename.text

    owner_get = api_client.client.get(f"/api/v1/files/{file_id}", headers=owner.auth_headers)
    assert owner_get.status_code == 200, owner_get.text
    assert owner_get.json()["name"] == "secret.txt"
    assert owner_get.json()["is_trashed"] is False
