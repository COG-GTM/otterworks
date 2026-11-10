"""Read access to the workspace share policy, falling back to defaults."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.share import (
    DEFAULT_ALLOW_NEVER,
    DEFAULT_EXPIRY_SECONDS,
    MAX_EXPIRY_SECONDS,
    MIN_EXPIRY_SECONDS,
    WorkspaceSharePolicy,
)


def current_workspace_id() -> str:
    return settings.workspace_id


def default_share_policy(workspace_id: str) -> WorkspaceSharePolicy:
    """Unsaved policy carrying the workspace defaults (30d / 1h / 365d / no never)."""
    return WorkspaceSharePolicy(
        workspace_id=workspace_id,
        default_expiry_seconds=DEFAULT_EXPIRY_SECONDS,
        min_expiry_seconds=MIN_EXPIRY_SECONDS,
        max_expiry_seconds=MAX_EXPIRY_SECONDS,
        allow_never=DEFAULT_ALLOW_NEVER,
        updated_by=None,
        updated_at=None,
    )


class SharePolicyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_saved(self, workspace_id: str | None = None) -> WorkspaceSharePolicy | None:
        return await self.db.get(WorkspaceSharePolicy, workspace_id or current_workspace_id())

    async def get_effective(self, workspace_id: str | None = None) -> WorkspaceSharePolicy:
        """Saved policy for the workspace, or the defaults when no row exists."""
        workspace_id = workspace_id or current_workspace_id()
        saved = await self.get_saved(workspace_id)
        return saved if saved is not None else default_share_policy(workspace_id)
