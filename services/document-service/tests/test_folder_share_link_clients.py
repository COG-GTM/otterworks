"""OTW-67 tests for the file-service client and the sharing-policy client.

Scenarios: OTW-63 US1 (ownership and listing come from file-service) and US2
("Given no policy has been configured, Then the default is 30 days, the minimum
is 1 day and the maximum is 90 days"), plus the SHARING_POLICY_URL fallback.
"""

import uuid

import httpx
import pytest

from app.services.file_service_client import (
    FileServiceClient,
    FileServiceUnavailableError,
    FolderInfo,
)
from app.services.sharing_policy import FALLBACK_POLICY, SharingPolicy, SharingPolicyClient

FOLDER_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
POLICY_URL = "http://admin-service:8089/api/v1/admin/sharing_policy"


def _file(i: int) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": f"f{i}.txt",
        "mime_type": "text/plain",
        "size_bytes": i,
        "s3_key": "ignored",
        "folder_id": str(FOLDER_ID),
        "owner_id": str(OWNER_ID),
        "version": 1,
        "is_trashed": False,
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-02T10:30:00.123456Z",
    }


def _files_client(handler) -> FileServiceClient:
    return FileServiceClient("http://file-service:8082", transport=httpx.MockTransport(handler))


# US1 / ownership: the folder's owner is read from file-service GET /api/v1/folders/{id}
async def test_us1_get_folder_reads_owner_from_file_service():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/folders/{FOLDER_ID}"
        return httpx.Response(200, json={
            "id": str(FOLDER_ID), "name": "Specs", "parent_id": None,
            "owner_id": str(OWNER_ID), "created_at": "x", "updated_at": "x",
        })

    folder = await _files_client(handler).get_folder(FOLDER_ID)
    assert folder == FolderInfo(id=FOLDER_ID, name="Specs", owner_id=OWNER_ID)


async def test_us1_get_folder_unknown_returns_none():
    folder = await _files_client(lambda r: httpx.Response(404, json={})).get_folder(FOLDER_ID)
    assert folder is None


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, json={"x": 1})])
async def test_us1_get_folder_errors_raise_unavailable(response):
    with pytest.raises(FileServiceUnavailableError):
        await _files_client(lambda r: response).get_folder(FOLDER_ID)


async def test_us1_get_folder_unreachable_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(FileServiceUnavailableError):
        await _files_client(handler).get_folder(FOLDER_ID)


# US1 / read-only view: every page of the folder's files is listed via GET /api/v1/files
async def test_us1_list_folder_files_follows_pages():
    all_files = [_file(i) for i in range(150)]
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        page, size = int(params["page"]), int(params["page_size"])
        batch = all_files[(page - 1) * size: page * size]
        return httpx.Response(200, json={"files": batch, "total": 150, "page": page,
                                         "page_size": size})

    folder = FolderInfo(id=FOLDER_ID, name="Specs", owner_id=OWNER_ID)
    files = await _files_client(handler).list_folder_files(folder)

    assert len(files) == 150
    assert [p["page"] for p in seen] == ["1", "2"]
    assert all(p["folder_id"] == str(FOLDER_ID) and p["owner_id"] == str(OWNER_ID) for p in seen)
    assert files[3].size == 3
    assert files[3].mime_type == "text/plain"
    assert files[3].updated_at.isoformat() == "2026-11-02T10:30:00.123456+00:00"


async def test_us1_list_folder_files_error_raises_unavailable():
    folder = FolderInfo(id=FOLDER_ID, name="Specs", owner_id=OWNER_ID)
    with pytest.raises(FileServiceUnavailableError):
        await _files_client(lambda r: httpx.Response(503)).list_folder_files(folder)


# US2 / Given no policy has been configured (SHARING_POLICY_URL unset), Then 30 / 1 / 90.
async def test_us2_unset_policy_url_falls_back_to_30_1_90(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SHARING_POLICY_URL", raising=False)
    policy = await SharingPolicyClient().get_policy("Bearer x")
    assert policy == SharingPolicy(30, 1, 90)
    assert policy == FALLBACK_POLICY


# Policy is read from SHARING_POLICY_URL with the caller's authorization.
async def test_us2_policy_read_from_sharing_policy_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHARING_POLICY_URL", POLICY_URL)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"default_expiry_days": 7, "min_expiry_days": 2,
                                         "max_expiry_days": 14})

    policy = await SharingPolicyClient(transport=httpx.MockTransport(handler)).get_policy(
        "Bearer abc"
    )
    assert policy == SharingPolicy(7, 2, 14)
    assert str(seen[0].url) == POLICY_URL
    assert seen[0].headers["Authorization"] == "Bearer abc"


# Unreachable or broken policy service: fall back to 30 / 1 / 90.
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(401, json={"error": "Missing authorization token"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"default_expiry_days": 30}),
        # outside the hard limits: never trusted
        httpx.Response(200, json={"default_expiry_days": 30, "min_expiry_days": 1,
                                  "max_expiry_days": 365}),
        httpx.Response(200, json={"default_expiry_days": 50, "min_expiry_days": 1,
                                  "max_expiry_days": 40}),
        httpx.Response(200, json={"default_expiry_days": 5, "min_expiry_days": 0,
                                  "max_expiry_days": 40}),
    ],
)
async def test_us2_bad_policy_response_falls_back(response):
    client = SharingPolicyClient(POLICY_URL, transport=httpx.MockTransport(lambda r: response))
    assert await client.get_policy(None) == FALLBACK_POLICY


async def test_us2_unreachable_policy_service_falls_back():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    client = SharingPolicyClient(POLICY_URL, transport=httpx.MockTransport(handler))
    assert await client.get_policy("Bearer abc") == FALLBACK_POLICY
