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


def test_file_and_folder_operations_are_restricted_to_owner(api_client):
    owner = api_client.register_user("file-authz-owner")
    viewer = api_client.register_user("file-authz-viewer")
    stranger = api_client.register_user("file-authz-stranger")

    folder_response = api_client.client.post(
        "/api/v1/folders",
        headers=owner.auth_headers,
        json={"name": f"Private Folder {api_client.run_id}", "owner_id": owner.id},
    )
    api_client.assert_gateway_route_available(folder_response, "/api/v1/folders")
    assert folder_response.status_code == 201, folder_response.text
    folder_id = folder_response.json()["id"]
    api_client.created_folders.append(folder_id)

    upload_response = api_client.client.post(
        "/api/v1/files/upload",
        headers=owner.auth_headers,
        files={"file": ("private.txt", b"owner only", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    file_id = upload_response.json()["file"]["id"]
    api_client.created_files.append(file_id)

    # shared_by in the body is ignored; the share is attributed to the caller.
    share_response = api_client.client.post(
        f"/api/v1/files/{file_id}/share",
        headers=owner.auth_headers,
        json={"shared_with": viewer.id, "permission": "viewer", "shared_by": stranger.id},
    )
    assert share_response.status_code == 201, share_response.text
    assert share_response.json()["share"]["shared_by"] == owner.id

    # A share recipient can read and download, and sees only their own share.
    viewer_get = api_client.client.get(f"/api/v1/files/{file_id}", headers=viewer.auth_headers)
    assert viewer_get.status_code == 200, viewer_get.text
    assert [s["shared_with"] for s in viewer_get.json()["shared_with"]] == [viewer.id]
    viewer_download = api_client.client.get(
        f"/api/v1/files/{file_id}/download", headers=viewer.auth_headers
    )
    assert viewer_download.status_code == 200, viewer_download.text

    # Neither the viewer nor a stranger can manage the file.
    for user in (viewer, stranger):
        h = user.auth_headers
        attempts = [
            api_client.client.delete(f"/api/v1/files/{file_id}", headers=h),
            api_client.client.patch(f"/api/v1/files/{file_id}/rename", headers=h, json={"name": "pwned"}),
            api_client.client.put(f"/api/v1/files/{file_id}/move", headers=h, json={"folder_id": None}),
            api_client.client.post(f"/api/v1/files/{file_id}/trash", headers=h),
            api_client.client.post(f"/api/v1/files/{file_id}/restore", headers=h),
            api_client.client.post(
                f"/api/v1/files/{file_id}/share",
                headers=h,
                json={"shared_with": user.id, "permission": "editor", "shared_by": owner.id},
            ),
            api_client.client.delete(f"/api/v1/files/{file_id}/share/{viewer.id}", headers=h),
            api_client.client.get(f"/api/v1/folders/{folder_id}", headers=h),
            api_client.client.put(f"/api/v1/folders/{folder_id}", headers=h, json={"name": "pwned"}),
            api_client.client.delete(f"/api/v1/folders/{folder_id}", headers=h),
        ]
        for response in attempts:
            assert response.status_code == 403, (response.request.method, response.request.url, response.text)

    # A stranger cannot read the file at all.
    for path in (f"/api/v1/files/{file_id}", f"/api/v1/files/{file_id}/download", f"/api/v1/files/{file_id}/versions"):
        response = api_client.client.get(path, headers=stranger.auth_headers)
        assert response.status_code == 403, (path, response.text)

    # A stranger cannot move their own file into the owner's folder.
    stranger_upload = api_client.client.post(
        "/api/v1/files/upload",
        headers=stranger.auth_headers,
        files={"file": ("mine.txt", b"stranger", "text/plain")},
    )
    assert stranger_upload.status_code == 201, stranger_upload.text
    stranger_file_id = stranger_upload.json()["file"]["id"]
    move_into_foreign = api_client.client.put(
        f"/api/v1/files/{stranger_file_id}/move",
        headers=stranger.auth_headers,
        json={"folder_id": folder_id},
    )
    assert move_into_foreign.status_code == 403, move_into_foreign.text
    assert api_client.client.delete(
        f"/api/v1/files/{stranger_file_id}", headers=stranger.auth_headers
    ).status_code == 204

    # The owner still has full control.
    assert api_client.client.get(f"/api/v1/folders/{folder_id}", headers=owner.auth_headers).status_code == 200
    rename = api_client.client.patch(
        f"/api/v1/files/{file_id}/rename", headers=owner.auth_headers, json={"name": "renamed.txt"}
    )
    assert rename.status_code == 200, rename.text
    unshare = api_client.client.delete(f"/api/v1/files/{file_id}/share/{viewer.id}", headers=owner.auth_headers)
    assert unshare.status_code == 204, unshare.text
    revoked = api_client.client.get(f"/api/v1/files/{file_id}/download", headers=viewer.auth_headers)
    assert revoked.status_code == 403, revoked.text

    assert api_client.client.delete(f"/api/v1/files/{file_id}", headers=owner.auth_headers).status_code == 204
    api_client.created_files.remove(file_id)
    assert api_client.client.delete(f"/api/v1/folders/{folder_id}", headers=owner.auth_headers).status_code == 204
    api_client.created_folders.remove(folder_id)
