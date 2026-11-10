"""Client for file-service folder and file metadata (folders live in file-service)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import httpx
import structlog

logger = structlog.get_logger()

FILE_SERVICE_URL_ENV = "FILE_SERVICE_URL"
DEFAULT_FILE_SERVICE_URL = "http://file-service:8082"
REQUEST_TIMEOUT_SECONDS = 5.0
# file-service caps page_size at 100.
FILES_PAGE_SIZE = 100


class FileServiceUnavailableError(RuntimeError):
    """file-service could not be reached or answered with an unexpected error."""


@dataclass(frozen=True)
class FolderInfo:
    id: UUID
    name: str
    owner_id: UUID


@dataclass(frozen=True)
class FolderFile:
    id: UUID
    name: str
    size: int
    mime_type: str
    updated_at: datetime


class FileServiceClient:
    """Reads folders and their files from file-service's /api/v1/folders and /api/v1/files."""

    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        url = base_url or os.environ.get(FILE_SERVICE_URL_ENV) or DEFAULT_FILE_SERVICE_URL
        self._base_url = url.rstrip("/")
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        )

    async def get_folder(self, folder_id: UUID) -> FolderInfo | None:
        """Return the folder, or ``None`` if file-service does not know it."""
        try:
            async with self._client() as client:
                resp = await client.get(f"/api/v1/folders/{folder_id}")
        except httpx.HTTPError as exc:
            logger.warning("file_service_unreachable", error=str(exc))
            raise FileServiceUnavailableError("file-service unreachable") from exc

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning("file_service_folder_error", status=resp.status_code)
            raise FileServiceUnavailableError(f"file-service returned {resp.status_code}")
        try:
            data = resp.json()
            return FolderInfo(
                id=UUID(str(data["id"])),
                name=str(data["name"]),
                owner_id=UUID(str(data["owner_id"])),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise FileServiceUnavailableError("unexpected folder payload") from exc

    async def list_folder_files(self, folder: FolderInfo) -> list[FolderFile]:
        """Return every non-trashed file directly inside ``folder``."""
        files: list[FolderFile] = []
        page = 1
        try:
            async with self._client() as client:
                while True:
                    resp = await client.get(
                        "/api/v1/files",
                        params={
                            "folder_id": str(folder.id),
                            "owner_id": str(folder.owner_id),
                            "page": page,
                            "page_size": FILES_PAGE_SIZE,
                        },
                    )
                    if resp.status_code != 200:
                        logger.warning("file_service_files_error", status=resp.status_code)
                        raise FileServiceUnavailableError(
                            f"file-service returned {resp.status_code}"
                        )
                    data = resp.json()
                    batch = data.get("files", [])
                    files.extend(_parse_file(item) for item in batch)
                    if not batch or len(files) >= int(data.get("total", 0)):
                        return files
                    page += 1
        except httpx.HTTPError as exc:
            logger.warning("file_service_unreachable", error=str(exc))
            raise FileServiceUnavailableError("file-service unreachable") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise FileServiceUnavailableError("unexpected files payload") from exc


def _parse_file(item: dict) -> FolderFile:
    return FolderFile(
        id=UUID(str(item["id"])),
        name=str(item["name"]),
        size=int(item["size_bytes"]),
        mime_type=str(item["mime_type"]),
        updated_at=datetime.fromisoformat(str(item["updated_at"]).replace("Z", "+00:00")),
    )


def get_file_service_client() -> FileServiceClient:
    return FileServiceClient()
