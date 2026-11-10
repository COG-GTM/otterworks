"""Document CRUD API endpoints."""

import asyncio
import os
import random
from uuid import UUID

import jwt
import redis as redis_lib
import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.schemas.document import (
    DocumentCreate,
    DocumentFromTemplate,
    DocumentListResponse,
    DocumentPatch,
    DocumentResponse,
    DocumentUpdate,
    DocumentVersionResponse,
)
from app.services.audit_client import AuditDeliveryError
from app.services.document_query_repository import DocumentQueryRepository
from app.services.document_service import DocumentService
from app.services.expiring_share_links import (
    ExpiringShareLinkService,
    ExpiryOutOfBoundsError,
    InvalidPolicyError,
    LinkExpiredError,
    is_expired,
    link_to_dict,
)
from app.services.export_archive import ExportArchive
from app.services.share_link import ShareLinkService

logger = structlog.get_logger()
router = APIRouter()

DEFAULT_SORT = "updated_at"
DEFAULT_DIRECTION = "desc"

_redis_client: redis_lib.Redis | None = None


def _get_redis() -> redis_lib.Redis:
    """Return a shared Redis client (lazy-initialised)."""
    global _redis_client
    if _redis_client is None:
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        _redis_client = redis_lib.Redis(
            host=host, port=port, decode_responses=True, socket_timeout=1,
        )
    return _redis_client


def _chaos_active(key: str) -> bool:
    """Return True if the given chaos flag is set in Redis."""
    try:
        return bool(_get_redis().exists(key))
    except Exception:
        return False


async def _maybe_inject_latency() -> None:
    """Inject 3-5s delay when the slow_queries chaos flag is active."""
    if _chaos_active("chaos:document-service:slow_queries"):
        delay = random.uniform(3.0, 5.0)
        logger.warning("chaos_latency_injected", delay_seconds=round(delay, 2))
        await asyncio.sleep(delay)


def _get_jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "")


def _extract_user_id(request: Request) -> UUID | None:
    """Extract user ID from the Authorization JWT."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        secret = _get_jwt_secret()
        if secret:
            try:
                payload = jwt.decode(token, secret, algorithms=["HS256", "HS384"])
                user_id_str = payload.get("user_id") or payload.get("sub")
                if user_id_str:
                    return UUID(str(user_id_str))
            except (jwt.PyJWTError, ValueError):
                pass
        else:
            forwarded_user_id = request.headers.get("X-User-ID")
            if forwarded_user_id:
                try:
                    return UUID(str(forwarded_user_id))
                except ValueError:
                    pass

    return None


def _require_user_id(request: Request) -> UUID:
    user_id = _extract_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _ensure_owner(document: object, user_id: UUID) -> None:
    if getattr(document, "owner_id", None) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")


WORKSPACE_POLICY_ROLES = {"ADMIN", "OWNER"}


def _jwt_claims(request: Request) -> dict:
    auth_header = request.headers.get("Authorization")
    secret = _get_jwt_secret()
    if not (auth_header and auth_header.startswith("Bearer ") and secret):
        return {}
    try:
        return jwt.decode(auth_header[len("Bearer "):], secret, algorithms=["HS256", "HS384"])
    except jwt.PyJWTError:
        return {}


def _workspace_id(request: Request) -> str:
    """Workspace scope for share-link policy; no workspace entity exists yet (OTW-82)."""
    claim = _jwt_claims(request).get("workspace_id")
    header = None if _get_jwt_secret() else request.headers.get("X-Workspace-ID")
    return str(claim or header or settings.default_workspace_id)


def _roles(request: Request) -> set[str]:
    if _get_jwt_secret():
        roles = _jwt_claims(request).get("roles") or []
    else:
        roles = (request.headers.get("X-User-Roles") or "").split(",")
    return {str(r).strip().upper() for r in roles if str(r).strip()}


class ShareLinkCreate(BaseModel):
    expires_in_days: int | None = Field(default=None, ge=1)


class ShareLinkExpiryUpdate(BaseModel):
    expires_in_days: int = Field(ge=1)


class SharePolicyUpdate(BaseModel):
    default_expiry_days: int
    min_expiry_days: int
    max_expiry_days: int


def _audit_unavailable(exc: AuditDeliveryError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Audit service unavailable; change was not saved",
    )


async def _do_create_document(
    body: DocumentCreate,
    request: Request,
    db: AsyncSession,
) -> DocumentResponse:
    if not body.owner_id:
        extracted_id = _extract_user_id(request)
        if not extracted_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="owner_id is required: provide it in the body or authenticate via JWT",
            )
        body.owner_id = extracted_id

    service = DocumentService(db)
    document = await service.create(body)
    logger.info("document_created", document_id=str(document.id))
    return document


@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    body: DocumentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new document."""
    await _maybe_inject_latency()
    return await _do_create_document(body, request, db)


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_document_no_slash(
    body: DocumentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new document (no trailing slash)."""
    await _maybe_inject_latency()
    return await _do_create_document(body, request, db)


@router.get("/search", response_model=DocumentListResponse)
async def search_documents(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search documents by title or content."""
    await _maybe_inject_latency()
    service = DocumentService(db)
    items, total = await service.search(q, page=page, size=size)
    return DocumentListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=service.paginate(total, page, size),
    )


@router.get("/exports", response_class=PlainTextResponse)
async def read_export(name: str = Query(..., min_length=1)):
    """Return a previously rendered export from the export archive."""
    archive = ExportArchive()
    try:
        return archive.read_export(name)
    except (OSError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Export not found") from exc


@router.get("/shared", response_model=DocumentResponse)
async def get_shared_document(
    document_id: UUID,
    token: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """Return a document through its read-only share link.

    Persisted links expire (410, never extended); links minted before persisted
    links existed are validated statelessly and are not retroactively expired.
    """
    links = ExpiringShareLinkService(db)
    link = await links.find_by_token(document_id, token)
    if link is not None:
        if is_expired(link):
            try:
                await links.record_expired(link)
            except AuditDeliveryError:
                logger.error("share_link_expired_audit_failed", link_id=str(link.id))
            raise HTTPException(
                status_code=status.HTTP_410_GONE, detail="This share link has expired"
            )
    elif not ShareLinkService().verify_token(str(document_id), token):
        raise HTTPException(status_code=403, detail="Invalid share token")
    document = await DocumentService(db).get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


async def _do_list_documents(
    owner_id: UUID | None,
    folder_id: UUID | None,
    page: int,
    size: int,
    db: AsyncSession,
) -> DocumentListResponse:
    await _maybe_inject_latency()
    service = DocumentService(db)
    items, total = await service.list_documents(
        owner_id=owner_id, folder_id=folder_id, page=page, size=size
    )
    return DocumentListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=service.paginate(total, page, size),
    )


async def _do_filter_documents(
    owner_id: UUID | None,
    folder_id: UUID | None,
    title: str | None,
    content_type: str | None,
    sort: str,
    direction: str,
    page: int,
    size: int,
    db: AsyncSession,
) -> DocumentListResponse:
    await _maybe_inject_latency()
    repo = DocumentQueryRepository(db)
    filters = {
        "owner_id": str(owner_id) if owner_id else None,
        "title_contains": title,
        "content_type": content_type,
        "folder_id": str(folder_id) if folder_id else None,
    }
    try:
        total = await repo.count_documents(**filters)
        rows = await repo.search_documents(
            **filters,
            sort=sort,
            direction=direction,
            limit=size,
            offset=(page - 1) * size,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid filter: {exc}") from exc
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        size=size,
        pages=DocumentService.paginate(total, page, size),
    )


def _is_filtered(
    title: str | None, content_type: str | None, sort: str, direction: str
) -> bool:
    """Whether the request needs the metadata-filter query path.

    Caller-chosen ordering only exists on that path, so a request that asks for
    one goes there too rather than silently getting the default order.
    """
    return (
        title is not None
        or content_type is not None
        or sort != DEFAULT_SORT
        or direction != DEFAULT_DIRECTION
    )


@router.get("/share-policy")
async def get_share_policy(request: Request, db: AsyncSession = Depends(get_db)):
    """Return the workspace's share-link expiry policy."""
    _require_user_id(request)
    policy = await ExpiringShareLinkService(db).get_policy(_workspace_id(request))
    return policy.as_dict()


@router.put("/share-policy")
async def update_share_policy(
    body: SharePolicyUpdate, request: Request, db: AsyncSession = Depends(get_db)
):
    """Set the workspace default expiry and the bounds users may choose within."""
    user_id = _require_user_id(request)
    if not _roles(request) & WORKSPACE_POLICY_ROLES:
        raise HTTPException(
            status_code=403, detail="Only workspace owners can change the share policy"
        )
    try:
        policy = await ExpiringShareLinkService(db).set_policy(
            _workspace_id(request),
            user_id,
            body.default_expiry_days,
            body.min_expiry_days,
            body.max_expiry_days,
        )
    except InvalidPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AuditDeliveryError as exc:
        raise _audit_unavailable(exc) from exc
    logger.info("share_policy_updated", workspace_id=policy.workspace_id)
    return policy.as_dict()


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    request: Request,
    owner_id: UUID | None = None,
    folder_id: UUID | None = None,
    title: str | None = None,
    content_type: str | None = None,
    sort: str = DEFAULT_SORT,
    direction: str = DEFAULT_DIRECTION,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List documents with optional filtering and pagination."""
    effective_owner = owner_id or _extract_user_id(request)
    if _is_filtered(title, content_type, sort, direction):
        return await _do_filter_documents(
            effective_owner,
            folder_id,
            title,
            content_type,
            sort,
            direction,
            page,
            size,
            db,
        )
    return await _do_list_documents(effective_owner, folder_id, page, size, db)


@router.get(
    "",
    response_model=DocumentListResponse,
    include_in_schema=False,
)
async def list_documents_no_slash(
    request: Request,
    owner_id: UUID | None = None,
    folder_id: UUID | None = None,
    title: str | None = None,
    content_type: str | None = None,
    sort: str = DEFAULT_SORT,
    direction: str = DEFAULT_DIRECTION,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List documents (no trailing slash)."""
    effective_owner = owner_id or _extract_user_id(request)
    if _is_filtered(title, content_type, sort, direction):
        return await _do_filter_documents(
            effective_owner,
            folder_id,
            title,
            content_type,
            sort,
            direction,
            page,
            size,
            db,
        )
    return await _do_list_documents(effective_owner, folder_id, page, size, db)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a document by ID."""
    await _maybe_inject_latency()
    user_id = _require_user_id(request)
    service = DocumentService(db)
    document = await service.get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(document, user_id)
    return document


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: UUID,
    body: DocumentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Full replace of a document."""
    await _maybe_inject_latency()
    user_id = _require_user_id(request)
    service = DocumentService(db)
    existing = await service.get(document_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(existing, user_id)
    document = await service.update(document_id, body)
    logger.info("document_updated", document_id=str(document_id))
    return document


@router.patch("/{document_id}", response_model=DocumentResponse)
async def patch_document(
    document_id: UUID,
    body: DocumentPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Partial update of a document."""
    await _maybe_inject_latency()
    user_id = _require_user_id(request)
    service = DocumentService(db)
    existing = await service.get(document_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(existing, user_id)
    document = await service.patch(document_id, body)
    logger.info("document_patched", document_id=str(document_id))
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a document (soft delete)."""
    await _maybe_inject_latency()
    user_id = _require_user_id(request)
    service = DocumentService(db)
    existing = await service.get(document_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(existing, user_id)
    await service.delete(document_id)
    logger.info("document_deleted", document_id=str(document_id))


@router.get("/{document_id}/versions", response_model=list[DocumentVersionResponse])
async def list_versions(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List document versions."""
    user_id = _require_user_id(request)
    service = DocumentService(db)
    document = await service.get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(document, user_id)
    versions = await service.list_versions(document_id)
    return versions


@router.post(
    "/{document_id}/versions/{version_id}/restore",
    response_model=DocumentResponse,
)
async def restore_version(
    document_id: UUID,
    version_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Restore a document to a previous version."""
    user_id = _require_user_id(request)
    service = DocumentService(db)
    existing = await service.get(document_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Document or version not found")
    _ensure_owner(existing, user_id)
    document = await service.restore_version(document_id, version_id)
    if not document:
        raise HTTPException(
            status_code=404, detail="Document or version not found"
        )
    logger.info(
        "document_version_restored",
        document_id=str(document_id),
        version_id=str(version_id),
    )
    return document


async def _owned_document(document_id: UUID, request: Request, db: AsyncSession) -> UUID:
    user_id = _require_user_id(request)
    document = await DocumentService(db).get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(document, user_id)
    return user_id


@router.post("/{document_id}/share")
async def create_share_link(
    document_id: UUID,
    request: Request,
    body: ShareLinkCreate | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Mint an expiring read-only share link (workspace default unless overridden)."""
    user_id = await _owned_document(document_id, request, db)
    try:
        link = await ExpiringShareLinkService(db).create(
            document_id,
            _workspace_id(request),
            user_id,
            body.expires_in_days if body else None,
        )
    except ExpiryOutOfBoundsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AuditDeliveryError as exc:
        raise _audit_unavailable(exc) from exc
    logger.info("share_link_created", document_id=str(document_id), link_id=str(link.id))
    return link_to_dict(link)


@router.get("/{document_id}/share-links")
async def list_share_links(
    document_id: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    """List a document's share links with their expiry."""
    await _owned_document(document_id, request, db)
    links = await ExpiringShareLinkService(db).list_for_document(document_id)
    return [link_to_dict(link) for link in links]


@router.patch("/{document_id}/share-links/{link_id}")
async def update_share_link_expiry(
    document_id: UUID,
    link_id: UUID,
    body: ShareLinkExpiryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Change a link's expiry within the workspace bounds; expired links stay expired."""
    user_id = await _owned_document(document_id, request, db)
    service = ExpiringShareLinkService(db)
    link = await service.get_link(document_id, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    try:
        link = await service.change_expiry(link, user_id, body.expires_in_days)
    except LinkExpiredError as exc:
        raise HTTPException(status_code=410, detail="This share link has expired") from exc
    except ExpiryOutOfBoundsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AuditDeliveryError as exc:
        raise _audit_unavailable(exc) from exc
    logger.info("share_link_expiry_changed", document_id=str(document_id), link_id=str(link_id))
    return link_to_dict(link)


@router.get("/{document_id}/export")
async def export_document(
    document_id: UUID,
    request: Request,
    format: str = Query("markdown", pattern="^(pdf|html|markdown)$"),  # noqa: A002
    db: AsyncSession = Depends(get_db),
):
    """Export a document in the requested format."""
    user_id = _require_user_id(request)
    service = DocumentService(db)
    document = await service.get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(document, user_id)

    body, content_type = service.export_document(document, format)
    return PlainTextResponse(content=body, media_type=content_type)


@router.post(
    "/from-template/{template_id}",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_from_template(
    template_id: UUID,
    body: DocumentFromTemplate,
    db: AsyncSession = Depends(get_db),
):
    """Create a document from a template."""
    service = DocumentService(db)
    document = await service.create_from_template(template_id, body)
    if not document:
        raise HTTPException(status_code=404, detail="Template not found")
    logger.info(
        "document_created_from_template",
        document_id=str(document.id),
        template_id=str(template_id),
    )
    return document
