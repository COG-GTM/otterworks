"""Folder share link endpoints (OTW-29): owner management + public recipient access."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _require_user_id
from app.config import settings
from app.db.session import get_db
from app.models.document import Document
from app.models.share import FolderShareLink, WorkspaceSharePolicy
from app.schemas.document import DocumentResponse
from app.schemas.folder_share_link import (
    FolderShareLinkCreated,
    FolderShareLinkList,
    FolderShareLinkResponse,
    SharedFolderDocument,
    SharedFolderResponse,
    ShareLinkExpiryRequest,
)
from app.services.document_service import DocumentService
from app.services.folder_directory import (
    FolderDirectory,
    FolderLookupError,
    get_folder_directory,
)
from app.services.folder_share_tokens import (
    MAX_TOKEN_LENGTH,
    ShareLinkKeyMissingError,
    generate_token,
    hash_token,
    token_matches,
)
from app.services.share_audit import ShareAuditPublisher, get_share_audit_publisher
from app.services.share_policy_repository import SharePolicyRepository, current_workspace_id
from app.services.workspace_owner import is_workspace_owner

logger = structlog.get_logger()
router = APIRouter()


class ExpiryPolicyError(Exception):
    """Requested expiry falls outside the workspace share policy (HTTP 422)."""

    def __init__(self, detail: str, policy: WorkspaceSharePolicy) -> None:
        super().__init__(detail)
        self.detail = detail
        self.min_expiry_seconds = policy.min_expiry_seconds
        self.max_expiry_seconds = policy.max_expiry_seconds
        self.allow_never = policy.allow_never


async def expiry_policy_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ExpiryPolicyError)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.detail,
            "min_expiry_seconds": exc.min_expiry_seconds,
            "max_expiry_seconds": exc.max_expiry_seconds,
            "allow_never": exc.allow_never,
        },
    )


def resolve_expiry(
    body: ShareLinkExpiryRequest, policy: WorkspaceSharePolicy, *, require_choice: bool
) -> timedelta | None:
    """Expiry offset from now allowed by the policy; ``None`` means never expires."""
    if body.never and body.expires_in_seconds is not None:
        raise ExpiryPolicyError("Send either expires_in_seconds or never, not both", policy)
    if body.never:
        if not policy.allow_never:
            raise ExpiryPolicyError("Links that never expire are not allowed", policy)
        return None
    seconds = body.expires_in_seconds
    if seconds is None:
        if require_choice:
            raise ExpiryPolicyError("Send expires_in_seconds or never", policy)
        seconds = policy.default_expiry_seconds
    elif not policy.min_expiry_seconds <= seconds <= policy.max_expiry_seconds:
        raise ExpiryPolicyError(
            f"expires_in_seconds must be between {policy.min_expiry_seconds} "
            f"and {policy.max_expiry_seconds}",
            policy,
        )
    return timedelta(seconds=seconds)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _db_now(db: AsyncSession) -> datetime:
    """Database clock, so expiry checks agree across replicas."""
    now = (await db.execute(select(func.now()))).scalar_one()
    if isinstance(now, str):  # SQLite returns CURRENT_TIMESTAMP as text
        now = datetime.fromisoformat(now)
    return _aware(now)  # type: ignore[return-value]


def _link_view(link: FolderShareLink, now: datetime) -> FolderShareLinkResponse:
    return FolderShareLinkResponse(
        id=link.id,
        folder_id=link.folder_id,
        created_by=link.created_by,
        created_at=_aware(link.created_at),  # type: ignore[arg-type]
        expires_at=_aware(link.expires_at),
        revoked_at=_aware(link.revoked_at),
        status=link.status_at(now),
    )


def _audit_value(link: FolderShareLink) -> dict:
    expires_at = _aware(link.expires_at)
    revoked_at = _aware(link.revoked_at)
    return {
        "folder_id": str(link.folder_id),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "revoked_at": revoked_at.isoformat() if revoked_at else None,
    }


def _hash(token: str) -> str:
    try:
        return hash_token(token)
    except ShareLinkKeyMissingError as exc:
        logger.error("share_link_hmac_key_missing")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Folder share links are not configured",
        ) from exc


async def _require_folder_owner(
    folders: FolderDirectory, folder_id: UUID, user_id: UUID
) -> None:
    try:
        folder = await folders.get_folder(folder_id)
    except FolderLookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Folder lookup failed"
        ) from exc
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    if folder.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")


async def _get_managed_link(
    db: AsyncSession, link_id: UUID, request: Request, user_id: UUID
) -> FolderShareLink:
    link = await db.get(FolderShareLink, link_id)
    if link is None or link.workspace_id != current_workspace_id():
        raise HTTPException(status_code=404, detail="Share link not found")
    if link.created_by != user_id and not is_workspace_owner(request, user_id):
        raise HTTPException(status_code=403, detail="Access denied")
    return link


@router.post(
    "/folders/{folder_id}/share-links",
    response_model=FolderShareLinkCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder_share_link(
    folder_id: UUID,
    request: Request,
    body: ShareLinkExpiryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    folders: FolderDirectory = Depends(get_folder_directory),
    audit: ShareAuditPublisher = Depends(get_share_audit_publisher),
):
    """Create a read-only link to every document in the folder."""
    user_id = _require_user_id(request)
    await _require_folder_owner(folders, folder_id, user_id)
    workspace_id = current_workspace_id()
    policy = await SharePolicyRepository(db).get_effective(workspace_id)
    expiry = resolve_expiry(body or ShareLinkExpiryRequest(), policy, require_choice=False)

    token = generate_token()
    now = await _db_now(db)
    link = FolderShareLink(
        token_hash=_hash(token),
        folder_id=folder_id,
        workspace_id=workspace_id,
        created_by=user_id,
        created_at=now,
        expires_at=now + expiry if expiry is not None else None,
    )
    db.add(link)
    await db.commit()

    logger.info("folder_share_link_created", link_id=str(link.id), folder_id=str(folder_id))
    await audit.emit(
        "share_link_created",
        str(user_id),
        workspace_id,
        "share_link",
        str(link.id),
        None,
        {**_audit_value(link), "created_by": str(user_id)},
    )
    view = _link_view(link, now)
    return FolderShareLinkCreated(
        **view.model_dump(),
        token=token,
        url=f"{settings.public_web_url.rstrip('/')}/shared-folder/{token}",
    )


@router.get("/folders/{folder_id}/share-links", response_model=FolderShareLinkList)
async def list_folder_share_links(
    folder_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    folders: FolderDirectory = Depends(get_folder_directory),
):
    """List the folder's links with their status (active / expired / revoked)."""
    user_id = _require_user_id(request)
    await _require_folder_owner(folders, folder_id, user_id)
    result = await db.execute(
        select(FolderShareLink)
        .where(
            FolderShareLink.folder_id == folder_id,
            FolderShareLink.workspace_id == current_workspace_id(),
        )
        .order_by(FolderShareLink.created_at.desc())
    )
    now = await _db_now(db)
    return FolderShareLinkList(items=[_link_view(link, now) for link in result.scalars()])


@router.patch("/share-links/{link_id}", response_model=FolderShareLinkResponse)
async def update_folder_share_link(
    link_id: UUID,
    body: ShareLinkExpiryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    audit: ShareAuditPublisher = Depends(get_share_audit_publisher),
):
    """Change an active link's expiry (counted from now) within the workspace policy."""
    user_id = _require_user_id(request)
    link = await _get_managed_link(db, link_id, request, user_id)
    now = await _db_now(db)
    current = link.status_at(now)
    if current != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Share link {current}; create a new link instead",
        )
    policy = await SharePolicyRepository(db).get_effective(link.workspace_id)
    expiry = resolve_expiry(body, policy, require_choice=True)

    old_value = _audit_value(link)
    link.expires_at = now + expiry if expiry is not None else None
    await db.commit()

    logger.info("folder_share_link_updated", link_id=str(link.id))
    await audit.emit(
        "share_link_updated",
        str(user_id),
        link.workspace_id,
        "share_link",
        str(link.id),
        old_value,
        _audit_value(link),
    )
    return _link_view(link, now)


@router.delete("/share-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_folder_share_link(
    link_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    audit: ShareAuditPublisher = Depends(get_share_audit_publisher),
):
    """Revoke a link; later use returns 410. Revoking twice is a no-op."""
    user_id = _require_user_id(request)
    link = await _get_managed_link(db, link_id, request, user_id)
    if link.revoked_at is None:
        old_value = _audit_value(link)
        link.revoked_at = await _db_now(db)
        await db.commit()
        logger.info("folder_share_link_revoked", link_id=str(link.id))
        await audit.emit(
            "share_link_revoked",
            str(user_id),
            link.workspace_id,
            "share_link",
            str(link.id),
            old_value,
            _audit_value(link),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _audit_expired_once(
    db: AsyncSession, link: FolderShareLink, audit: ShareAuditPublisher
) -> None:
    """Emit share_link_expired only for the request that claims expired_audited_at."""
    result = await db.execute(
        update(FolderShareLink)
        .where(FolderShareLink.id == link.id, FolderShareLink.expired_audited_at.is_(None))
        .values(expired_audited_at=func.now())
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if result.rowcount == 1:  # type: ignore[attr-defined]
        await audit.emit(
            "share_link_expired",
            None,
            link.workspace_id,
            "share_link",
            str(link.id),
            {**_audit_value(link), "status": "active"},
            {**_audit_value(link), "status": "expired"},
        )


async def _recipient_link(
    db: AsyncSession, token: str, audit: ShareAuditPublisher
) -> FolderShareLink:
    not_found = HTTPException(status_code=404, detail="Share link not found")
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise not_found
    result = await db.execute(
        select(FolderShareLink).where(
            FolderShareLink.token_hash == _hash(token),
            FolderShareLink.workspace_id == current_workspace_id(),
        )
    )
    link = result.scalar_one_or_none()
    if link is None or not token_matches(token, link.token_hash):
        raise not_found
    current = link.status_at(await _db_now(db))
    if current == "revoked":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Share link revoked")
    if current == "expired":
        await _audit_expired_once(db, link, audit)
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Share link expired")
    return link


@router.get("/shared-folders/{token}", response_model=SharedFolderResponse)
async def open_shared_folder(
    token: str,
    db: AsyncSession = Depends(get_db),
    audit: ShareAuditPublisher = Depends(get_share_audit_publisher),
):
    """Public: list the non-deleted documents in the shared folder (read-only)."""
    link = await _recipient_link(db, token, audit)
    result = await db.execute(
        select(Document)
        .where(Document.folder_id == link.folder_id, Document.is_deleted.is_(False))
        .order_by(Document.updated_at.desc())
    )
    return SharedFolderResponse(
        folder_id=link.folder_id,
        expires_at=_aware(link.expires_at),
        documents=[SharedFolderDocument.model_validate(doc) for doc in result.scalars()],
    )


@router.get("/shared-folders/{token}/documents/{document_id}", response_model=DocumentResponse)
async def read_shared_folder_document(
    token: str,
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    audit: ShareAuditPublisher = Depends(get_share_audit_publisher),
):
    """Public: read one document from the shared folder; documents elsewhere are 404."""
    link = await _recipient_link(db, token, audit)
    document = await DocumentService(db).get(document_id)
    if document is None or document.folder_id != link.folder_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return document
