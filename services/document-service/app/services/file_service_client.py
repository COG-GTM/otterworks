"""Read-only client for file-service folder metadata and folder file listings."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.config import settings

# file-service caps page_size at 100.
FILE_PAGE_SIZE = 100


class FileServiceError(Exception):
    """file-service could not be reached or returned an unexpected response."""


class FolderNotFoundError(FileServiceError):
    """file-service has no folder with the requested id."""


class FileServiceClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout, transport=self.transport
        )

    async def get_folder(self, folder_id: UUID) -> dict[str, Any]:
        async with self._client() as client:
            response = await self._get(client, f"/api/v1/folders/{folder_id}")
        if response.status_code == httpx.codes.NOT_FOUND:
            raise FolderNotFoundError(str(folder_id))
        return self._json(response)

    async def list_folder_files(self, folder_id: UUID) -> list[dict[str, Any]]:
        """Return every non-trashed file directly inside the folder.

        No X-User-ID or owner filter is sent, so file-service lists the folder as-is
        and never runs its per-owner demo seeding.
        """
        files: list[dict[str, Any]] = []
        page = 1
        async with self._client() as client:
            while True:
                response = await self._get(
                    client,
                    "/api/v1/files",
                    params={
                        "folder_id": str(folder_id),
                        "page": page,
                        "page_size": FILE_PAGE_SIZE,
                    },
                )
                body = self._json(response)
                batch = body.get("files") or []
                files.extend(batch)
                total = int(body.get("total", len(files)))
                if not batch or len(files) >= total:
                    return files
                page += 1

    @staticmethod
    async def _get(
        client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        try:
            return await client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise FileServiceError(f"file-service request failed: {exc}") from exc

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code != httpx.codes.OK:
            raise FileServiceError(f"file-service returned HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise FileServiceError("file-service returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise FileServiceError("file-service returned an unexpected body")
        return body


def get_file_service_client() -> FileServiceClient:
    return FileServiceClient(
        settings.file_service_url, timeout=settings.file_service_timeout_seconds
    )
