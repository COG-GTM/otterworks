"""OTW-67 black-box flow: folder share links through the API gateway (OTW-63 US1, US3, US4)."""

import uuid

import pytest


pytestmark = pytest.mark.api_flow

LINKS = "/api/v1/folder-share-links"


def test_folder_share_link_create_open_edit_revoke(api_client):
    owner = api_client.register_user("folder-share-owner")
    stranger = api_client.register_user("folder-share-stranger")

    folder_response = api_client.client.post(
        "/api/v1/folders",
        headers=owner.auth_headers,
        json={"name": f"Shared Folder {api_client.run_id}", "owner_id": owner.id},
    )
    assert folder_response.status_code == 201, folder_response.text
    folder = folder_response.json()
    api_client.created_folders.append(folder["id"])

    upload_response = api_client.client.post(
        "/api/v1/files/upload",
        headers=owner.auth_headers,
        files={"file": ("shared.txt", b"hello shared folder", "text/plain")},
        data={"folder_id": folder["id"]},
    )
    assert upload_response.status_code == 201, upload_response.text
    file_id = upload_response.json()["file"]["id"]
    api_client.created_files.append(file_id)

    # Management endpoints require a JWT at the gateway.
    unauthenticated = api_client.client.post(LINKS, json={"folder_id": folder["id"]})
    api_client.assert_gateway_route_available(unauthenticated, LINKS)
    assert unauthenticated.status_code == 401, unauthenticated.text

    # US1: a non-owner gets 403.
    forbidden = api_client.client.post(
        LINKS, headers=stranger.auth_headers, json={"folder_id": folder["id"]}
    )
    assert forbidden.status_code == 403, forbidden.text

    # US3: "never" / out-of-range expiry is rejected.
    for bad in (0, 91, "never"):
        rejected = api_client.client.post(
            LINKS, headers=owner.auth_headers,
            json={"folder_id": folder["id"], "expires_in_days": bad},
        )
        assert rejected.status_code == 422, rejected.text

    # US1: the owner creates a link; the raw token is returned only here.
    created_response = api_client.client.post(
        LINKS, headers=owner.auth_headers, json={"folder_id": folder["id"]}
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    token = created["token"]

    # US1: anyone (no JWT) holding the token gets a read-only view of the folder.
    shared = api_client.client.get(f"{LINKS}/shared", params={"token": token})
    assert shared.status_code == 200, shared.text
    body = shared.json()
    assert body["folder"]["id"] == folder["id"]
    assert [f["id"] for f in body["files"]] == [file_id]
    assert body["expires_at"] == created["expires_at"]

    # Owner listing never returns tokens.
    listed = api_client.client.get(
        LINKS, headers=owner.auth_headers, params={"folder_id": folder["id"]}
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["status"] == "active"
    assert token not in listed.text

    # US3: edit expiry within bounds.
    patched = api_client.client.patch(
        f"{LINKS}/{created['id']}", headers=owner.auth_headers, json={"expires_in_days": 7}
    )
    assert patched.status_code == 200, patched.text

    # US4: unknown token -> 404.
    unknown = api_client.client.get(f"{LINKS}/shared", params={"token": uuid.uuid4().hex})
    assert unknown.status_code == 404, unknown.text

    # US3: revoke takes effect at once; US4: revoked -> 410.
    revoked = api_client.client.delete(f"{LINKS}/{created['id']}", headers=owner.auth_headers)
    assert revoked.status_code == 204, revoked.text
    gone = api_client.client.get(f"{LINKS}/shared", params={"token": token})
    assert gone.status_code == 410, gone.text
    assert gone.json() == {"detail": "link_revoked"}

    # US3: a revoked link cannot be edited.
    conflict = api_client.client.patch(
        f"{LINKS}/{created['id']}", headers=owner.auth_headers, json={"expires_in_days": 30}
    )
    assert conflict.status_code == 409, conflict.text
