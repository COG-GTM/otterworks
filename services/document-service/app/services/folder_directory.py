"""Folder lookups against file-service, which owns folders (DynamoDB)."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()


@dataclass(frozen=True)
class FolderInfo:
    id: UUID
    owner_id: UUID


class FolderLookupError(Exception):
    """file-service could not answer the folder lookup."""


class FolderDirectory(Protocol):
    async def get_folder(self, folder_id: UUID) -> FolderInfo | None:
        """Return the folder, or None when it does not exist."""


class FileServiceFolderDirectory:
    """Reads folders through file-service ``GET /api/v1/folders/{id}``."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def get_folder(self, folder_id: UUID) -> FolderInfo | None:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout, transport=self.transport
            ) as client:
                resp = await client.get(f"/api/v1/folders/{folder_id}")
        except httpx.HTTPError as exc:
            logger.warning("folder_lookup_failed", folder_id=str(folder_id), error=str(exc))
            raise FolderLookupError(str(exc)) from exc

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning(
                "folder_lookup_failed", folder_id=str(folder_id), status=resp.status_code
            )
            raise FolderLookupError(f"file-service returned {resp.status_code}")
        try:
            data = resp.json()
            return FolderInfo(id=UUID(str(data["id"])), owner_id=UUID(str(data["owner_id"])))
        except (ValueError, KeyError, TypeError) as exc:
            raise FolderLookupError("unexpected folder payload from file-service") from exc


def get_folder_directory() -> FolderDirectory:
    """FastAPI dependency; tests override it with an in-memory directory."""
    return FileServiceFolderDirectory(
        settings.file_service_url, timeout=settings.file_service_timeout_seconds
    )
