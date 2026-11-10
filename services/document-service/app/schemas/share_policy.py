"""Workspace share-policy request/response schemas (OTW-45)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.models.share_link import MAX_SHARE_DAYS, MIN_SHARE_DAYS


class SharePolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_id: str
    default_days: int
    max_days: int
    updated_at: datetime | None = None
    updated_by: UUID | None = None


class SharePolicyUpdate(BaseModel):
    """Body of ``PUT /api/v1/workspace/share-policy``.

    Both fields are whole days. ``null``, strings such as ``"never"`` and values outside
    1..90 are rejected with 422; there is no non-expiring option. ``max_days`` may be
    omitted to keep the workspace's current maximum.
    """

    model_config = ConfigDict(extra="forbid")

    default_days: StrictInt = Field(ge=MIN_SHARE_DAYS, le=MAX_SHARE_DAYS)
    max_days: StrictInt | None = Field(default=None, ge=MIN_SHARE_DAYS, le=MAX_SHARE_DAYS)

    @field_validator("max_days", mode="before")
    @classmethod
    def _reject_explicit_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError(
                "max_days must be a whole number of days; omit it to keep the current maximum"
            )
        return value
