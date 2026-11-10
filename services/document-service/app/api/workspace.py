"""Workspace share-policy API (OTW-45).

Any authenticated user may read the policy; only a workspace owner may change it. A change
applies only to links created afterwards: existing links keep their ``expires_at``.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _require_user_id
from app.db.session import get_db
from app.models.share_link import WorkspaceSharePolicy
from app.schemas.share_policy import SharePolicyResponse, SharePolicyUpdate
from app.services.share_link_repository import (
    EffectiveSharePolicy,
    InvalidSharePolicyError,
    WorkspaceSharePolicyRepository,
)
from app.services.share_policy_events import emit_policy_changed_event
from app.services.workspace import is_workspace_owner, resolve_workspace_id

logger = structlog.get_logger()
router = APIRouter()


def _require_workspace_owner(request: Request) -> UUID:
    user_id = _require_user_id(request)
    if not is_workspace_owner(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a workspace owner can change the share policy",
        )
    return user_id


async def _lock_current_policy(db: AsyncSession, workspace_id: str) -> EffectiveSharePolicy:
    """Read the policy in force with its row locked until the update commits.

    An omitted ``max_days`` is filled from this read, so it must not race another owner's save.
    A missing row is created at the built-in values first so there is always a row to lock;
    the caller rolls it back with the lock if the update is rejected.
    """
    insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
    created = await db.execute(
        insert(WorkspaceSharePolicy)
        .values(workspace_id=workspace_id)
        .on_conflict_do_nothing(index_elements=["workspace_id"])
    )
    row = (
        await db.execute(
            select(WorkspaceSharePolicy)
            .where(WorkspaceSharePolicy.workspace_id == workspace_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if created.rowcount:
        return EffectiveSharePolicy.builtin(workspace_id)
    return EffectiveSharePolicy.from_row(row)


@router.get("/share-policy", response_model=SharePolicyResponse)
async def get_share_policy(request: Request, db: AsyncSession = Depends(get_db)):
    _require_user_id(request)
    return await WorkspaceSharePolicyRepository(db).get(resolve_workspace_id(request))


@router.put("/share-policy", response_model=SharePolicyResponse)
async def update_share_policy(
    body: SharePolicyUpdate,
    request: Request,
    user_id: UUID = Depends(_require_workspace_owner),
    db: AsyncSession = Depends(get_db),
):
    workspace_id = resolve_workspace_id(request)
    repo = WorkspaceSharePolicyRepository(db)
    old = await _lock_current_policy(db, workspace_id)
    max_days = body.max_days if body.max_days is not None else old.max_days
    try:
        new = await repo.upsert(
            workspace_id,
            default_days=body.default_days,
            max_days=max_days,
            updated_by=user_id,
        )
    except InvalidSharePolicyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    logger.info(
        "workspace_share_policy_updated",
        workspace_id=workspace_id,
        default_days=new.default_days,
        max_days=new.max_days,
    )
    await emit_policy_changed_event(old, new, actor_id=user_id, workspace_id=workspace_id)
    return new
