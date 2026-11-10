"""Expiring, read-only folder share links (OTW-44, parent OTW-41)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _require_user_id
from app.config import settings
from app.db.session import get_db
from app.models.share_link import MAX_SHARE_DAYS, MIN_SHARE_DAYS, ShareLink
from app.schemas.share_link import (
    ResolvedShareLinkResponse,
    ShareLinkCreate,
    ShareLinkResponse,
    ShareLinkUpdate,
)
from app.services.file_service_client import (
    FileServiceClient,
    FileServiceError,
    FolderNotFoundError,
    get_file_service_client,
)
from app.services.share_link_events import (
    SHARE_LINK_CREATED,
    SHARE_LINK_EXPIRED,
    SHARE_LINK_EXPIRY_CHANGED,
    emit_share_link_event,
)
from app.services.share_link_repository import (
    ShareLinkRepository,
    WorkspaceSharePolicyRepository,
)
from app.services.workspace import resolve_workspace_id

logger = structlog.get_logger()
router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo; every stored timestamp is UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_expired(link: ShareLink, now: datetime) -> bool:
    return _as_utc(link.expires_at) <= now


def _owned_by(file: dict, owner_id: UUID) -> bool:
    try:
        return UUID(str(file.get("owner_id"))) == owner_id
    except ValueError:
        return False


def _link_url(token: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/s/{token}"


def _to_response(link: ShareLink) -> ShareLinkResponse:
    return ShareLinkResponse(
        id=link.id,
        token=link.token,
        url=_link_url(link.token),
        resource_type=link.resource_type,
        resource_id=link.resource_id,
        expires_at=_as_utc(link.expires_at),
        created_at=_as_utc(link.created_at),
        expired_at=_as_utc(link.expired_at) if link.expired_at else None,
    )


def _expired_response(link: ShareLink) -> JSONResponse:
    expired_at = _as_utc(link.expired_at) if link.expired_at else None
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={
            "error": "link_expired",
            "expired_at": expired_at.isoformat() if expired_at else None,
        },
        headers={"Cache-Control": "no-store"},
    )


async def _check_expiry_bounds(db: AsyncSession, workspace_id: str, days: int) -> None:
    policy = await WorkspaceSharePolicyRepository(db).get(workspace_id)
    max_days = min(policy.max_days, MAX_SHARE_DAYS)
    if not MIN_SHARE_DAYS <= days <= max_days:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "expires_in_days_out_of_range",
                "message": f"expires_in_days must be between {MIN_SHARE_DAYS} and {max_days}",
                "min_days": MIN_SHARE_DAYS,
                "max_days": max_days,
            },
        )


async def _mark_expired(repo: ShareLinkRepository, link: ShareLink, now: datetime) -> None:
    """Record expiry once; the expiry itself is never extended."""
    if await repo.mark_expired(link, now):
        await emit_share_link_event(
            SHARE_LINK_EXPIRED,
            link,
            actor=None,
            old_value={"expires_at": _as_utc(link.expires_at).isoformat()},
            new_value={"expired_at": now.isoformat()},
            occurred_at=now,
        )
        logger.info("share_link_expired", share_link_id=str(link.id))


async def _require_owned_folder(files: FileServiceClient, folder_id: UUID, user_id: UUID) -> None:
    try:
        folder = await files.get_folder(folder_id)
    except FolderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Folder not found") from exc
    except FileServiceError as exc:
        logger.warning("share_link_file_service_error", error=str(exc))
        raise HTTPException(status_code=502, detail="file-service unavailable") from exc
    if str(folder.get("owner_id")) != str(user_id):
        raise HTTPException(status_code=403, detail="Only the folder owner can share it")


@router.post("", response_model=ShareLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_share_link(
    body: ShareLinkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
):
    """Create an expiring read-only link to a folder the caller owns."""
    user_id = _require_user_id(request)
    workspace_id = resolve_workspace_id(request)
    if body.expires_in_days is None:
        days = (await WorkspaceSharePolicyRepository(db).get(workspace_id)).default_days
    else:
        days = body.expires_in_days
        await _check_expiry_bounds(db, workspace_id, days)
    await _require_owned_folder(files, body.resource_id, user_id)

    now = _utcnow()
    link = await ShareLinkRepository(db).create(
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        workspace_id=workspace_id,
        created_by=user_id,
        expires_at=now + timedelta(days=days),
    )
    await emit_share_link_event(
        SHARE_LINK_CREATED,
        link,
        actor=user_id,
        old_value=None,
        new_value={"expires_at": _as_utc(link.expires_at).isoformat()},
        occurred_at=now,
    )
    logger.info("folder_share_link_created", share_link_id=str(link.id), expires_in_days=days)
    return _to_response(link)


@router.get("", response_model=list[ShareLinkResponse])
async def list_share_links(
    request: Request,
    resource_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's links for a resource, newest first."""
    user_id = _require_user_id(request)
    links = await ShareLinkRepository(db).list_for_resource(resource_id, created_by=user_id)
    return [_to_response(link) for link in links]


@router.get("/resolve/{token}", response_model=ResolvedShareLinkResponse)
async def resolve_share_link(
    token: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
):
    """Public: list a shared folder read-only, or 410 once the link has expired."""
    repo = ShareLinkRepository(db)
    link = await repo.get_by_token(token)
    if link is None:
        raise HTTPException(status_code=404, detail="Share link not found")

    now = _utcnow()
    if _is_expired(link, now):
        await _mark_expired(repo, link, now)
        return _expired_response(link)

    try:
        folder = await files.get_folder(link.resource_id)
        folder_files = await files.list_folder_files(link.resource_id)
    except FolderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Shared folder not found") from exc
    except FileServiceError as exc:
        logger.warning("share_link_file_service_error", error=str(exc))
        raise HTTPException(status_code=502, detail="file-service unavailable") from exc

    # file-service does not stop other users moving their files into this folder, so
    # only the files of the folder owner (verified when the link was created) are shared.
    owned_files = [f for f in folder_files if _owned_by(f, link.created_by)]

    response.headers["Cache-Control"] = "no-store"
    return ResolvedShareLinkResponse.from_file_service(
        folder, owned_files, _as_utc(link.expires_at)
    )


@router.patch("/{link_id}", response_model=ShareLinkResponse)
async def update_share_link(
    link_id: UUID,
    body: ShareLinkUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Change a link's expiry to now + expires_in_days (link creator only)."""
    user_id = _require_user_id(request)
    repo = ShareLinkRepository(db)
    link = await repo.get(link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    if link.created_by != user_id:
        raise HTTPException(status_code=403, detail="Only the link owner can change it")

    now = _utcnow()
    if _is_expired(link, now):
        await _mark_expired(repo, link, now)
        return _expired_response(link)
    await _check_expiry_bounds(db, link.workspace_id, body.expires_in_days)

    old_expires_at = _as_utc(link.expires_at)
    link = await repo.update_expiry(link, now + timedelta(days=body.expires_in_days))
    await emit_share_link_event(
        SHARE_LINK_EXPIRY_CHANGED,
        link,
        actor=user_id,
        old_value={"expires_at": old_expires_at.isoformat()},
        new_value={"expires_at": _as_utc(link.expires_at).isoformat()},
        occurred_at=now,
    )
    logger.info("folder_share_link_expiry_changed", share_link_id=str(link.id))
    return _to_response(link)
