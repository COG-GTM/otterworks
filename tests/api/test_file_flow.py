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


def test_file_ids_are_scoped_to_owner_and_share_recipients(api_client):
    owner = api_client.register_user("file-authz-owner")
    viewer = api_client.register_user("file-authz-viewer")
    stranger = api_client.register_user("file-authz-stranger")

    upload_response = api_client.client.post(
        "/api/v1/files/upload",
        headers=owner.auth_headers,
        files={"file": ("private.txt", b"owner only", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    file_id = upload_response.json()["file"]["id"]
    api_client.created_files.append(file_id)
    base = f"/api/v1/files/{file_id}"

    share_response = api_client.client.post(
        f"{base}/share",
        headers=owner.auth_headers,
        json={"shared_with": viewer.id, "permission": "viewer", "shared_by": stranger.id},
    )
    assert share_response.status_code == 201, share_response.text
    assert share_response.json()["share"]["shared_by"] == owner.id

    attacks = [
        ("GET", base, None),
        ("GET", f"{base}/download", None),
        ("GET", f"{base}/versions", None),
        ("PUT", f"{base}/move", {"folder_id": None}),
        ("PATCH", f"{base}/rename", {"name": "pwned.txt"}),
        ("POST", f"{base}/trash", None),
        ("POST", f"{base}/restore", None),
        ("POST", f"{base}/share", {"shared_with": stranger.id, "permission": "editor"}),
        ("DELETE", f"{base}/share/{viewer.id}", None),
        ("DELETE", base, None),
    ]
    for method, path, body in attacks:
        response = api_client.client.request(method, path, headers=stranger.auth_headers, json=body)
        assert response.status_code == 404, f"stranger {method} {path}: {response.status_code}"

    viewer_get = api_client.client.get(base, headers=viewer.auth_headers)
    assert viewer_get.status_code == 200, viewer_get.text
    assert [s["shared_with"] for s in viewer_get.json()["shared_with"]] == [viewer.id]
    viewer_download = api_client.client.get(f"{base}/download", headers=viewer.auth_headers)
    assert viewer_download.status_code == 200, viewer_download.text

    for method, path, body in [
        ("PATCH", f"{base}/rename", {"name": "viewer.txt"}),
        ("POST", f"{base}/share", {"shared_with": viewer.id, "permission": "editor"}),
        ("POST", f"{base}/trash", None),
        ("DELETE", base, None),
    ]:
        response = api_client.client.request(method, path, headers=viewer.auth_headers, json=body)
        assert response.status_code == 404, f"viewer {method} {path}: {response.status_code}"

    owner_get = api_client.client.get(base, headers=owner.auth_headers)
    assert owner_get.status_code == 200, owner_get.text
    assert owner_get.json()["name"] == "private.txt"

    delete_response = api_client.client.delete(base, headers=owner.auth_headers)
    assert delete_response.status_code == 204, delete_response.text
    api_client.created_files.remove(file_id)


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
