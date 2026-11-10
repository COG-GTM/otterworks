"""Folder share-link API (OTW-67): create, list, update expiry, revoke, open.

Folders and their files live in file-service; expiry defaults and bounds come
from the workspace sharing policy. Only ``POST`` ever returns a raw token.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _require_user_id
from app.db.session import get_db
from app.models.folder_share_link import FolderShareLink, FolderShareLinkStatus
from app.schemas.folder_share_link import (
    FolderShareLinkCreate,
    FolderShareLinkCreated,
    FolderShareLinkGone,
    FolderShareLinkResponse,
    FolderShareLinkUpdate,
    SharedFolder,
    SharedFolderFile,
    SharedFolderResponse,
)
from app.services.file_service_client import (
    FileServiceClient,
    FileServiceUnavailableError,
    FolderInfo,
    get_file_service_client,
)
from app.services.folder_share_link_events import ShareLinkEventType, emit_share_link_event
from app.services.folder_share_link_service import FolderShareLinkService, as_utc, utcnow
from app.services.folder_share_token import ShareLinkSecretMissingError
from app.services.sharing_policy import (
    SharingPolicy,
    SharingPolicyClient,
    get_sharing_policy_client,
)

logger = structlog.get_logger()
router = APIRouter()

GONE_DETAIL = {
    FolderShareLinkStatus.EXPIRED: "link_expired",
    FolderShareLinkStatus.REVOKED: "link_revoked",
}


def _to_response(link: FolderShareLink) -> FolderShareLinkResponse:
    return FolderShareLinkResponse(
        id=link.id,
        folder_id=link.folder_id,
        created_by=link.created_by,
        created_at=as_utc(link.created_at),
        expires_at=as_utc(link.expires_at),
        revoked_at=as_utc(link.revoked_at) if link.revoked_at else None,
        status=link.status_at(utcnow()),
    )


def _expiry_value(link: FolderShareLink) -> dict[str, Any]:
    return {"expires_at": as_utc(link.expires_at).isoformat()}


def _policy_error(policy: SharingPolicy) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"expires_in_days must be between {policy.min_expiry_days} and "
            f"{policy.max_expiry_days}"
        ),
    )


async def _owned_folder(
    folder_id: UUID, user_id: UUID, files: FileServiceClient
) -> FolderInfo:
    """Return the folder if ``user_id`` owns it; 403 otherwise (including unknown folders)."""
    try:
        folder = await files.get_folder(folder_id, user_id)
    except FileServiceUnavailableError as exc:
        raise HTTPException(status_code=502, detail="file-service unavailable") from exc
    if folder is None or folder.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return folder


async def _owned_link(
    link_id: UUID,
    user_id: UUID,
    service: FolderShareLinkService,
    files: FileServiceClient,
    *,
    for_update: bool = False,
) -> FolderShareLink:
    link = await service.get(link_id, for_update=for_update)
    if link is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    await _owned_folder(link.folder_id, user_id, files)
    return link


@router.post(
    "",
    response_model=FolderShareLinkCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder_share_link(
    body: FolderShareLinkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
    policies: SharingPolicyClient = Depends(get_sharing_policy_client),
) -> FolderShareLinkCreated:
    user_id = _require_user_id(request)
    await _owned_folder(body.folder_id, user_id, files)

    policy = await policies.get_policy(request.headers.get("Authorization"))
    days = body.expires_in_days if body.expires_in_days is not None else policy.default_expiry_days
    if not policy.allows(days):
        raise _policy_error(policy)

    try:
        link, token = await FolderShareLinkService(db).create(body.folder_id, user_id, days)
    except ShareLinkSecretMissingError as exc:
        logger.error("share_link_secret_missing")
        raise HTTPException(status_code=503, detail="Share links are not configured") from exc

    await emit_share_link_event(
        ShareLinkEventType.CREATED, link, user_id, None, _expiry_value(link)
    )
    logger.info("folder_share_link_created", link_id=str(link.id), folder_id=str(link.folder_id))
    return FolderShareLinkCreated(
        id=link.id,
        folder_id=link.folder_id,
        token=token,
        expires_at=as_utc(link.expires_at),
        created_at=as_utc(link.created_at),
    )


@router.post(
    "/",
    response_model=FolderShareLinkCreated,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_folder_share_link_slash(
    body: FolderShareLinkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
    policies: SharingPolicyClient = Depends(get_sharing_policy_client),
) -> FolderShareLinkCreated:
    return await create_folder_share_link(body, request, db, files, policies)


@router.get("", response_model=list[FolderShareLinkResponse])
async def list_folder_share_links(
    request: Request,
    folder_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
) -> list[FolderShareLinkResponse]:
    user_id = _require_user_id(request)
    await _owned_folder(folder_id, user_id, files)
    links = await FolderShareLinkService(db).list_for_folder(folder_id)
    return [_to_response(link) for link in links]


@router.get("/", response_model=list[FolderShareLinkResponse], include_in_schema=False)
async def list_folder_share_links_slash(
    request: Request,
    folder_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
) -> list[FolderShareLinkResponse]:
    return await list_folder_share_links(request, folder_id, db, files)


@router.get(
    "/shared",
    response_model=SharedFolderResponse,
    responses={404: {"description": "Unknown token"}, 410: {"model": FolderShareLinkGone}},
)
async def open_shared_folder(
    token: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
):
    """Public read-only view of a folder through an active share link."""
    try:
        link = await FolderShareLinkService(db).find_by_token(token)
    except ShareLinkSecretMissingError as exc:
        logger.error("share_link_secret_missing")
        raise HTTPException(status_code=503, detail="Share links are not configured") from exc
    if link is None:
        raise HTTPException(status_code=404, detail="link_not_found")

    link_status = link.status_at(utcnow())
    if link_status is not FolderShareLinkStatus.ACTIVE:
        return JSONResponse(
            status_code=status.HTTP_410_GONE, content={"detail": GONE_DETAIL[link_status]}
        )

    try:
        folder = await files.get_folder(link.folder_id, link.created_by)
        if folder is None:
            raise HTTPException(status_code=404, detail="link_not_found")
        folder_files = await files.list_folder_files(folder)
    except FileServiceUnavailableError as exc:
        raise HTTPException(status_code=502, detail="file-service unavailable") from exc

    return SharedFolderResponse(
        folder=SharedFolder(id=folder.id, name=folder.name),
        files=[
            SharedFolderFile(
                id=f.id,
                name=f.name,
                size=f.size,
                mime_type=f.mime_type,
                updated_at=f.updated_at,
            )
            for f in folder_files
        ],
        expires_at=as_utc(link.expires_at),
    )


@router.patch("/{link_id}", response_model=FolderShareLinkResponse)
async def update_folder_share_link_expiry(
    link_id: UUID,
    body: FolderShareLinkUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
    policies: SharingPolicyClient = Depends(get_sharing_policy_client),
) -> FolderShareLinkResponse:
    """Set the link's lifetime to ``expires_in_days`` from its creation.

    The lifetime is anchored to ``created_at`` so repeated edits can never keep a
    link alive past the policy maximum. Expired or revoked links cannot be edited.
    """
    user_id = _require_user_id(request)
    service = FolderShareLinkService(db)
    link = await _owned_link(link_id, user_id, service, files, for_update=True)

    now = utcnow()
    if link.status_at(now) is not FolderShareLinkStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Share link is {link.status_at(now)}; create a new link instead",
        )

    policy = await policies.get_policy(request.headers.get("Authorization"))
    if not policy.allows(body.expires_in_days):
        raise _policy_error(policy)
    new_expires_at = as_utc(link.created_at) + timedelta(days=body.expires_in_days)
    if new_expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expires_in_days would set an expiry in the past",
        )

    if new_expires_at == as_utc(link.expires_at):
        return _to_response(link)

    old_value = _expiry_value(link)
    link = await service.set_expiry(link, new_expires_at)
    await emit_share_link_event(
        ShareLinkEventType.EXPIRY_UPDATED, link, user_id, old_value, _expiry_value(link)
    )
    return _to_response(link)


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_folder_share_link(
    link_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    files: FileServiceClient = Depends(get_file_service_client),
) -> Response:
    """Revoke a link; the record is kept. Revoking twice keeps the first revocation time."""
    user_id = _require_user_id(request)
    service = FolderShareLinkService(db)
    link = await _owned_link(link_id, user_id, service, files, for_update=True)
    if link.revoked_at is None:
        link = await service.revoke(link, utcnow())
        await emit_share_link_event(
            ShareLinkEventType.REVOKED,
            link,
            user_id,
            {"revoked_at": None},
            {"revoked_at": as_utc(link.revoked_at).isoformat()},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
