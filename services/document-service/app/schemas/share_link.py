"""Schemas for expiring share links and the workspace share policy (OTW-20)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SharePolicyResponse(BaseModel):
    workspace_id: str
    default_expiry_days: int
    min_expiry_days: int
    max_expiry_days: int

    model_config = {"from_attributes": True}


class SharePolicyUpdate(BaseModel):
    default_expiry_days: int = Field(..., ge=1)
    min_expiry_days: int = Field(..., ge=1)
    max_expiry_days: int = Field(..., ge=1)


class ShareLinkCreate(BaseModel):
    expires_in_days: int | None = None


class ShareLinkExpiryUpdate(BaseModel):
    expires_in_days: int


class ShareLinkResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    token: str
    created_by: uuid.UUID
    created_at: datetime
    expires_at: datetime
    expired: bool = False

    model_config = {"from_attributes": True}
