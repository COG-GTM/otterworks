"""Expiring share links and workspace share policy endpoints (OTW-53)."""

from datetime import datetime
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _ensure_owner, _get_jwt_secret, _require_user_id
from app.db.session import get_db
from app.models.sharing import DEFAULT_WORKSPACE_ID, ShareLink
from app.services.document_service import DocumentService
from app.services.share_link_store import (
    ExpiryPolicyError,
    PolicyValues,
    ShareLinkStore,
    as_aware,
    is_expired,
)

router = APIRouter()

WORKSPACE_OWNER_ROLES = {"ADMIN", "ROLE_ADMIN", "WORKSPACE_OWNER", "OWNER"}


class SharePolicyBody(BaseModel):
    default_expiry_days: int | None = Field(default=None, ge=1)
    min_expiry_days: int = Field(default=1, ge=1)
    max_expiry_days: int | None = Field(default=None, ge=1)
    allow_no_expiry: bool = True


class SharePolicyResponse(SharePolicyBody):
    workspace_id: str


class ShareLinkExpiryBody(BaseModel):
    expires_in_days: int | None = Field(default=None, ge=1)
    no_expiry: bool = False


class ShareLinkResponse(BaseModel):
    id: str
    link_id: str
    document_id: str
    token: str
    created_by: str
    created_at: datetime
    expires_at: datetime | None
    expired: bool


def _workspace_id(request: Request) -> str:
    return request.headers.get("X-Workspace-ID") or DEFAULT_WORKSPACE_ID


def _extract_roles(request: Request) -> set[str]:
    auth_header = request.headers.get("Authorization", "")
    secret = _get_jwt_secret()
    if secret and auth_header.startswith("Bearer "):
        try:
            payload = jwt.decode(
                auth_header[len("Bearer "):], secret, algorithms=["HS256", "HS384"]
            )
        except jwt.PyJWTError:
            return set()
        roles = payload.get("roles") or []
        if isinstance(roles, str):
            roles = [roles]
        if payload.get("role"):
            roles = [*roles, payload["role"]]
        return {str(r).upper() for r in roles}
    if not secret:
        header = request.headers.get("X-User-Roles", "")
        return {r.strip().upper() for r in header.split(",") if r.strip()}
    return set()


def _require_workspace_owner(request: Request) -> UUID:
    user_id = _require_user_id(request)
    if not _extract_roles(request) & WORKSPACE_OWNER_ROLES:
        raise HTTPException(
            status_code=403, detail="Only workspace owners can change sharing policy"
        )
    return user_id


def to_response(link: ShareLink) -> ShareLinkResponse:
    return ShareLinkResponse(
        id=str(link.id),
        link_id=str(link.id),
        document_id=str(link.document_id),
        token=link.token,
        created_by=str(link.created_by),
        created_at=as_aware(link.created_at),
        expires_at=as_aware(link.expires_at),
        expired=is_expired(link),
    )


def _policy_response(workspace_id: str, values: PolicyValues) -> SharePolicyResponse:
    return SharePolicyResponse(
        workspace_id=workspace_id,
        default_expiry_days=values.default_expiry_days,
        min_expiry_days=values.min_expiry_days,
        max_expiry_days=values.max_expiry_days,
        allow_no_expiry=values.allow_no_expiry,
    )


@router.get("/share-policy", response_model=SharePolicyResponse)
async def get_share_policy(request: Request, db: AsyncSession = Depends(get_db)):
    """Return the workspace share-link expiry policy (any signed-in user)."""
    _require_user_id(request)
    workspace_id = _workspace_id(request)
    values = await ShareLinkStore(db).get_policy(workspace_id)
    return _policy_response(workspace_id, values)


@router.put("/share-policy", response_model=SharePolicyResponse)
async def update_share_policy(
    body: SharePolicyBody, request: Request, db: AsyncSession = Depends(get_db)
):
    """Set the workspace default expiry and bounds (workspace owners only)."""
    actor_id = _require_workspace_owner(request)
    workspace_id = _workspace_id(request)
    values = PolicyValues(**body.model_dump())
    try:
        await ShareLinkStore(db).update_policy(workspace_id, values, actor_id)
    except ExpiryPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _policy_response(workspace_id, values)


async def _owned_document(document_id: UUID, request: Request, db: AsyncSession) -> UUID:
    user_id = _require_user_id(request)
    document = await DocumentService(db).get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(document, user_id)
    return user_id


@router.get("/{document_id}/share-links", response_model=list[ShareLinkResponse])
async def list_share_links(
    document_id: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    """List share links for a document (owner only)."""
    await _owned_document(document_id, request, db)
    links = await ShareLinkStore(db).list_links(document_id)
    return [to_response(link) for link in links]


@router.patch(
    "/{document_id}/share-links/{link_id}", response_model=ShareLinkResponse
)
async def update_share_link_expiry(
    document_id: UUID,
    link_id: UUID,
    body: ShareLinkExpiryBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Change a link's expiry within workspace bounds (owner only)."""
    user_id = await _owned_document(document_id, request, db)
    store = ShareLinkStore(db)
    link = await store.get_link(document_id, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    try:
        link = await store.change_expiry(
            link, user_id, expires_in_days=body.expires_in_days, no_expiry=body.no_expiry
        )
    except ExpiryPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return to_response(link)
