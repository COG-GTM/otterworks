"""Request/response schemas for folder share links (OTW-29)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ShareLinkExpiryRequest(BaseModel):
    """Expiry override: seconds from now, or ``never``; empty means workspace default."""

    expires_in_seconds: int | None = None
    never: bool = False


class FolderShareLinkResponse(BaseModel):
    id: UUID
    folder_id: UUID
    created_by: UUID
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    status: Literal["active", "expired", "revoked"]


class FolderShareLinkCreated(FolderShareLinkResponse):
    token: str
    url: str


class FolderShareLinkList(BaseModel):
    items: list[FolderShareLinkResponse]


class SharedFolderDocument(BaseModel):
    id: UUID
    title: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class SharedFolderResponse(BaseModel):
    folder_id: UUID
    expires_at: datetime | None
    documents: list[SharedFolderDocument]
