"""Request/response schemas for folder share links (OTW-44)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, StrictInt, model_validator


class ShareLinkCreate(BaseModel):
    resource_type: Literal["folder"]
    resource_id: UUID
    # Omitted means the workspace default. There is no "never": null is rejected.
    expires_in_days: StrictInt | None = None

    @model_validator(mode="after")
    def _reject_explicit_null(self) -> ShareLinkCreate:
        if "expires_in_days" in self.model_fields_set and self.expires_in_days is None:
            raise ValueError("expires_in_days cannot be null; links always expire")
        return self


class ShareLinkUpdate(BaseModel):
    expires_in_days: StrictInt


class ShareLinkResponse(BaseModel):
    id: UUID
    token: str
    url: str
    resource_type: str
    resource_id: UUID
    expires_at: datetime
    created_at: datetime
    expired_at: datetime | None = None


class SharedFolder(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SharedFile(BaseModel):
    id: UUID
    name: str
    mime_type: str | None = None
    size_bytes: int | None = None
    version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ResolvedShareLinkResponse(BaseModel):
    resource_type: Literal["folder"] = "folder"
    folder: SharedFolder
    files: list[SharedFile]
    expires_at: datetime

    @classmethod
    def from_file_service(
        cls, folder: dict[str, Any], files: list[dict[str, Any]], expires_at: datetime
    ) -> ResolvedShareLinkResponse:
        """Build the read-only view, keeping only display fields (no s3_key or owner_id)."""
        return cls(
            folder=SharedFolder.model_validate(folder),
            files=[SharedFile.model_validate(f) for f in files],
            expires_at=expires_at,
        )
