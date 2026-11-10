"""Pydantic schemas for folder share links (contract shared with OTW-67)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.folder_share_link import FolderShareLinkStatus

# Hard policy limits. The configured workspace policy (default/min/max, read from
# SHARING_POLICY_URL) can only narrow these; there is no "never expire".
POLICY_DEFAULT_EXPIRY_DAYS = 30
POLICY_MIN_EXPIRY_DAYS = 1
POLICY_MAX_EXPIRY_DAYS = 90


class FolderShareLinkCreate(BaseModel):
    folder_id: UUID
    expires_in_days: int | None = Field(
        default=None, ge=POLICY_MIN_EXPIRY_DAYS, le=POLICY_MAX_EXPIRY_DAYS
    )


class FolderShareLinkUpdate(BaseModel):
    expires_in_days: int = Field(ge=POLICY_MIN_EXPIRY_DAYS, le=POLICY_MAX_EXPIRY_DAYS)


class FolderShareLinkCreated(BaseModel):
    """Create response: the only payload that ever carries the raw token."""

    id: UUID
    folder_id: UUID
    token: str
    expires_at: datetime
    created_at: datetime


class FolderShareLinkResponse(BaseModel):
    id: UUID
    folder_id: UUID
    created_by: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    status: FolderShareLinkStatus

    model_config = {"from_attributes": True}


class SharedFolder(BaseModel):
    id: UUID
    name: str


class SharedFolderFile(BaseModel):
    id: UUID
    name: str
    size: int
    mime_type: str
    updated_at: datetime


class SharedFolderResponse(BaseModel):
    folder: SharedFolder
    files: list[SharedFolderFile]
    expires_at: datetime


class FolderShareLinkGone(BaseModel):
    detail: Literal["link_expired", "link_revoked"]
