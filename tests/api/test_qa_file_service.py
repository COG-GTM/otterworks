"""QA audit of file-service through the API gateway (see docs/qa/file-service.md).

Expected-secure behaviour that the service does not implement today is marked
``xfail(strict=True)`` with the finding id, so a fix turns the test red until
the marker is removed.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

pytestmark = pytest.mark.api_flow

MAX_UPLOAD_BYTES = 104_857_600


def _upload(api_client, user, name="qa.txt", data=b"0123456789abcdef", content_type="text/plain", **form):
    response = api_client.client.post(
        "/api/v1/files/upload",
        headers=user.auth_headers,
        files={"file": (name, data, content_type)},
        data=form or None,
    )
    assert response.status_code == 201, response.text
    file = response.json()["file"]
    api_client.created_files.append(file["id"])
    return file


def _folder(api_client, user, name, parent_id=None):
    response = api_client.client.post(
        "/api/v1/folders",
        headers=user.auth_headers,
        json={"name": name, "owner_id": user.id, "parent_id": parent_id},
    )
    assert response.status_code == 201, response.text
    folder = response.json()
    api_client.created_folders.append(folder["id"])
    return folder


def _browser_url(url: str) -> str:
    # Same rewrite the web client applies (frontend/client-app/src/lib/api.ts).
    return url.replace("://localstack:", "://localhost:")


@pytest.fixture
def alice_and_mallory(api_client):
    alice = api_client.register_user("qa-fs-alice")
    mallory = api_client.register_user("qa-fs-mallory")
    file = _upload(api_client, alice, name="payroll.csv", data=b"secret,data")
    folder = _folder(api_client, alice, f"QA HR {api_client.run_id}")
    return alice, mallory, file, folder


# ── Auth at the gateway ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/files"),
        ("POST", "/api/v1/files/upload"),
        ("GET", f"/api/v1/files/{uuid.uuid4()}"),
        ("GET", f"/api/v1/files/{uuid.uuid4()}/download"),
        ("GET", "/api/v1/folders"),
        ("GET", "/api/v1/files/trash"),
        ("GET", "/api/v1/files/shared"),
    ],
)
def test_file_routes_require_jwt(api_client, method, path):
    response = api_client.client.request(method, path)
    assert response.status_code == 401, response.text


def test_gateway_strips_spoofed_x_user_id(api_client):
    alice = api_client.register_user("qa-fs-spoof-a")
    bob = api_client.register_user("qa-fs-spoof-b")
    _upload(api_client, bob, name="bob-only.txt")
    response = api_client.client.get(
        "/api/v1/files",
        headers={**alice.auth_headers, "X-User-ID": bob.id},
        params={"owner_id": bob.id},
    )
    assert response.status_code == 200
    assert all(f["owner_id"] == alice.id for f in response.json()["files"])


# ── Upload / download ───────────────────────────────────────────────────


def test_upload_metadata_and_download_round_trip(api_client):
    user = api_client.register_user("qa-fs-upload")
    payload = b"otterworks-qa-" + uuid.uuid4().bytes
    file = _upload(api_client, user, name="round.bin", data=payload, content_type="application/octet-stream")
    assert file["owner_id"] == user.id
    assert file["size_bytes"] == len(payload)
    assert file["s3_key"] == f"files/{user.id}/{file['id']}"

    detail = api_client.client.get(f"/api/v1/files/{file['id']}", headers=user.auth_headers)
    assert detail.status_code == 200
    assert detail.json()["shared_with"] == []

    download = api_client.client.get(f"/api/v1/files/{file['id']}/download", headers=user.auth_headers)
    assert download.status_code == 200, download.text
    assert download.json()["expires_in_secs"] == 3600
    blob = httpx.get(_browser_url(download.json()["url"]), timeout=15)
    assert blob.status_code == 200
    assert blob.content == payload


def test_ranged_read_via_presigned_url(api_client):
    user = api_client.register_user("qa-fs-range")
    file = _upload(api_client, user, data=b"0123456789abcdef")
    url = api_client.client.get(f"/api/v1/files/{file['id']}/download", headers=user.auth_headers).json()["url"]
    part = httpx.get(_browser_url(url), headers={"Range": "bytes=2-5"}, timeout=15)
    assert part.status_code == 206
    assert part.content == b"2345"
    assert part.headers["content-range"] == "bytes 2-5/16"


@pytest.mark.xfail(strict=True, reason="FS-05: file-service has no streaming/ranged download endpoint; Range is ignored and JSON is returned")
def test_download_endpoint_honours_range_header(api_client):
    user = api_client.register_user("qa-fs-range-api")
    file = _upload(api_client, user)
    response = api_client.client.get(
        f"/api/v1/files/{file['id']}/download",
        headers={**user.auth_headers, "Range": "bytes=0-3"},
    )
    assert response.status_code == 206


def test_upload_validation(api_client):
    user = api_client.register_user("qa-fs-validate")
    empty = api_client.client.post(
        "/api/v1/files/upload", headers=user.auth_headers, files={"file": ("e.txt", b"", "text/plain")}
    )
    assert empty.status_code == 400
    assert api_client.assert_json_error(empty)["error"] == "bad_request"
    no_file = api_client.client.post(
        "/api/v1/files/upload", headers=user.auth_headers, data={"folder_id": ""}, files={"x": ("x", b"x")}
    )
    assert no_file.status_code == 400
    bad_folder = api_client.client.post(
        "/api/v1/files/upload",
        headers=user.auth_headers,
        files={"file": ("a.txt", b"x", "text/plain")},
        data={"folder_id": "not-a-uuid"},
    )
    assert bad_folder.status_code == 400


def test_upload_over_100mb_is_413(api_client):
    user = api_client.register_user("qa-fs-big")
    response = api_client.client.post(
        "/api/v1/files/upload",
        headers=user.auth_headers,
        files={"file": ("big.bin", b"\0" * (MAX_UPLOAD_BYTES + 1), "application/octet-stream")},
        timeout=120,
    )
    assert response.status_code == 413, response.text[:200]
    assert response.json()["error"] == "file_too_large"


@pytest.mark.xfail(strict=True, reason="FS-06: no file-type validation; text/html is stored and served with its declared MIME type")
def test_active_content_upload_is_rejected_or_neutralised(api_client):
    user = api_client.register_user("qa-fs-mime")
    response = api_client.client.post(
        "/api/v1/files/upload",
        headers=user.auth_headers,
        files={"file": ("x.html", b"<script>alert(1)</script>", "text/html")},
    )
    if response.status_code == 201:
        api_client.created_files.append(response.json()["file"]["id"])
    assert response.status_code == 415 or response.json()["file"]["mime_type"] != "text/html"


# ── Folders / rename / move / trash / restore / delete ─────────────────


def test_folder_move_rename_trash_restore_delete_flow(api_client):
    user = api_client.register_user("qa-fs-flow")
    parent = _folder(api_client, user, f"QA Parent {api_client.run_id}")
    child = _folder(api_client, user, "QA Child", parent_id=parent["id"])
    children = api_client.client.get(
        "/api/v1/folders", headers=user.auth_headers, params={"parent_id": parent["id"]}
    ).json()["folders"]
    assert [f["id"] for f in children] == [child["id"]]

    file = _upload(api_client, user, name="flow.txt")
    fid = file["id"]
    moved = api_client.client.put(
        f"/api/v1/files/{fid}/move", headers=user.auth_headers, json={"folder_id": child["id"]}
    )
    assert moved.status_code == 200 and moved.json()["folder_id"] == child["id"]
    in_folder = api_client.client.get(
        "/api/v1/files", headers=user.auth_headers, params={"folder_id": child["id"]}
    ).json()
    assert [f["id"] for f in in_folder["files"]] == [fid]

    renamed = api_client.client.patch(
        f"/api/v1/files/{fid}/rename", headers=user.auth_headers, json={"name": "  renamed.txt "}
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "renamed.txt"
    blank = api_client.client.patch(f"/api/v1/files/{fid}/rename", headers=user.auth_headers, json={"name": " "})
    assert blank.status_code == 400

    assert api_client.client.post(f"/api/v1/files/{fid}/trash", headers=user.auth_headers).json()["is_trashed"]
    trash = api_client.client.get("/api/v1/files/trash", headers=user.auth_headers).json()["files"]
    assert fid in [f["id"] for f in trash]
    listing = api_client.client.get("/api/v1/files", headers=user.auth_headers).json()["files"]
    assert fid not in [f["id"] for f in listing]

    restored = api_client.client.post(f"/api/v1/files/{fid}/restore", headers=user.auth_headers)
    assert restored.status_code == 200 and restored.json()["is_trashed"] is False

    assert api_client.client.delete(f"/api/v1/files/{fid}", headers=user.auth_headers).status_code == 204
    assert api_client.client.get(f"/api/v1/files/{fid}", headers=user.auth_headers).status_code == 404
    api_client.created_files.remove(fid)


@pytest.mark.parametrize(
    "method,path_tmpl,body",
    [
        ("GET", "/api/v1/files/{id}", None),
        ("GET", "/api/v1/files/{id}/download", None),
        ("PATCH", "/api/v1/files/{id}/rename", {"name": "x"}),
        ("PUT", "/api/v1/files/{id}/move", {"folder_id": None}),
        ("POST", "/api/v1/files/{id}/trash", None),
        ("POST", "/api/v1/files/{id}/restore", None),
        ("DELETE", "/api/v1/files/{id}", None),
        ("GET", "/api/v1/folders/{id}", None),
        ("PUT", "/api/v1/folders/{id}", {"name": "x"}),
    ],
)
def test_unknown_ids_are_404_and_malformed_ids_400(api_client, method, path_tmpl, body):
    user = api_client.register_user("qa-fs-404")
    missing = api_client.client.request(method, path_tmpl.format(id=uuid.uuid4()), headers=user.auth_headers, json=body)
    assert missing.status_code == 404, missing.text
    malformed = api_client.client.request(method, path_tmpl.format(id="nope"), headers=user.auth_headers, json=body)
    assert malformed.status_code == 400, malformed.text


@pytest.mark.xfail(strict=True, reason="FS-09: DELETE /folders/{id} returns 204 for a folder that does not exist")
def test_delete_unknown_folder_is_404(api_client):
    user = api_client.register_user("qa-fs-delfolder")
    assert api_client.client.delete(f"/api/v1/folders/{uuid.uuid4()}", headers=user.auth_headers).status_code == 404


@pytest.mark.xfail(strict=True, reason="FS-10: moving a file into a nonexistent folder is accepted")
def test_move_into_unknown_folder_is_rejected(api_client):
    user = api_client.register_user("qa-fs-move404")
    file = _upload(api_client, user)
    response = api_client.client.put(
        f"/api/v1/files/{file['id']}/move", headers=user.auth_headers, json={"folder_id": str(uuid.uuid4())}
    )
    assert response.status_code in (400, 404)


# ── Sharing ────────────────────────────────────────────────────────────


def test_share_shared_with_me_and_revoke(api_client):
    owner = api_client.register_user("qa-fs-sharer")
    friend = api_client.register_user("qa-fs-friend")
    file = _upload(api_client, owner, name="team.txt")
    def share(perm):
        return api_client.client.post(
            f"/api/v1/files/{file['id']}/share",
            headers=owner.auth_headers,
            json={"shared_with": friend.id, "permission": perm, "shared_by": owner.id},
        )

    first = share("viewer")
    assert first.status_code == 201, first.text
    assert share("viewer").status_code == 200
    updated = share("editor")
    assert updated.status_code == 200 and updated.json()["share"]["permission"] == "editor"
    assert updated.json()["share"]["id"] == first.json()["share"]["id"]

    shared = api_client.client.get("/api/v1/files/shared", headers=friend.auth_headers).json()["files"]
    assert file["id"] in [f["id"] for f in shared]
    friend_detail = api_client.client.get(f"/api/v1/files/{file['id']}", headers=friend.auth_headers)
    assert friend_detail.status_code == 200

    bad = api_client.client.post(
        f"/api/v1/files/{file['id']}/share",
        headers=owner.auth_headers,
        json={"shared_with": friend.id, "permission": "owner", "shared_by": owner.id},
    )
    assert bad.status_code in (400, 422)

    revoke = api_client.client.delete(f"/api/v1/files/{file['id']}/share/{friend.id}", headers=owner.auth_headers)
    assert revoke.status_code == 204
    again = api_client.client.delete(f"/api/v1/files/{file['id']}/share/{friend.id}", headers=owner.auth_headers)
    assert again.status_code == 404
    shared = api_client.client.get("/api/v1/files/shared", headers=friend.auth_headers).json()["files"]
    assert file["id"] not in [f["id"] for f in shared]


def test_activity_lists_upload_and_share(api_client):
    owner = api_client.register_user("qa-fs-activity")
    friend = api_client.register_user("qa-fs-activity-f")
    file = _upload(api_client, owner, name="activity.txt")
    api_client.client.post(
        f"/api/v1/files/{file['id']}/share",
        headers=owner.auth_headers,
        json={"shared_with": friend.id, "permission": "viewer", "shared_by": owner.id},
    )
    items = api_client.client.get("/api/v1/files/activity", headers=owner.auth_headers).json()["items"]
    kinds = {(i["type"], i["resource_id"]) for i in items}
    assert ("upload", file["id"]) in kinds and ("share", file["id"]) in kinds


# ── Ownership / IDOR (FS-01..FS-04) ────────────────────────────────────

IDOR = [
    ("FS-01", "GET", "/api/v1/files/{file}", None),
    ("FS-01", "GET", "/api/v1/files/{file}/download", None),
    ("FS-01", "GET", "/api/v1/files/{file}/versions", None),
    ("FS-02", "PATCH", "/api/v1/files/{file}/rename", {"name": "pwned.csv"}),
    ("FS-02", "PUT", "/api/v1/files/{file}/move", {"folder_id": None}),
    ("FS-02", "POST", "/api/v1/files/{file}/trash", None),
    ("FS-02", "POST", "/api/v1/files/{file}/restore", None),
    ("FS-02", "DELETE", "/api/v1/files/{file}", None),
    ("FS-03", "POST", "/api/v1/files/{file}/share", {"shared_with": "{mallory}", "permission": "editor", "shared_by": "{alice}"}),
    ("FS-04", "GET", "/api/v1/folders/{folder}", None),
    ("FS-04", "PUT", "/api/v1/folders/{folder}", {"name": "pwned"}),
    ("FS-04", "DELETE", "/api/v1/folders/{folder}", None),
]


@pytest.mark.parametrize(
    "finding,method,path_tmpl,body",
    [
        pytest.param(*case, id=f"{case[0]}-{case[1]}-{case[2].rsplit('}', 1)[-1] or 'root'}",
                     marks=pytest.mark.xfail(strict=True, reason=f"{case[0]}: no ownership check on {case[1]} {case[2]} (IDOR)"))
        for case in IDOR
    ],
)
def test_non_owner_is_denied(api_client, alice_and_mallory, finding, method, path_tmpl, body):
    alice, mallory, file, folder = alice_and_mallory
    path = path_tmpl.format(file=file["id"], folder=folder["id"])
    if body:
        body = {k: (v.format(alice=alice.id, mallory=mallory.id) if isinstance(v, str) else v) for k, v in body.items()}
    response = api_client.client.request(method, path, headers=mallory.auth_headers, json=body)
    assert response.status_code in (403, 404), f"{finding}: non-owner got {response.status_code}"


@pytest.mark.xfail(strict=True, reason="FS-03: non-owner can revoke another user's share")
def test_non_owner_cannot_revoke_share(api_client, alice_and_mallory):
    alice, mallory, file, _ = alice_and_mallory
    friend = api_client.register_user("qa-fs-idor-friend")
    api_client.client.post(
        f"/api/v1/files/{file['id']}/share",
        headers=alice.auth_headers,
        json={"shared_with": friend.id, "permission": "viewer", "shared_by": alice.id},
    )
    response = api_client.client.delete(f"/api/v1/files/{file['id']}/share/{friend.id}", headers=mallory.auth_headers)
    assert response.status_code in (403, 404)


@pytest.mark.xfail(strict=True, reason="FS-04: POST /folders trusts body owner_id over the authenticated user")
def test_create_folder_cannot_target_another_owner(api_client, alice_and_mallory):
    alice, mallory, _, _ = alice_and_mallory
    response = api_client.client.post(
        "/api/v1/folders", headers=mallory.auth_headers, json={"name": "planted", "owner_id": alice.id}
    )
    if response.status_code == 201:
        api_client.created_folders.append(response.json()["id"])
    assert response.status_code == 403 or response.json()["owner_id"] == mallory.id


def test_list_endpoints_do_not_leak_other_users_files(api_client, alice_and_mallory):
    alice, mallory, file, folder = alice_and_mallory
    for path, key in [("/api/v1/files", "files"), ("/api/v1/files/trash", "files"), ("/api/v1/folders", "folders")]:
        response = api_client.client.get(path, headers=mallory.auth_headers, params={"owner_id": alice.id})
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()[key]]
        assert file["id"] not in ids and folder["id"] not in ids, path
