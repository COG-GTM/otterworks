"""Workspace share policy and per-link expiry management (OTW-20)."""

from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _ensure_owner, _get_jwt_secret, _require_user_id
from app.db.session import get_db
from app.models.share_link import ShareLink
from app.schemas.share_link import (
    ShareLinkExpiryUpdate,
    ShareLinkResponse,
    SharePolicyResponse,
    SharePolicyUpdate,
)
from app.services.document_service import DocumentService
from app.services.share_link_store import (
    ExpiryOutOfBoundsError,
    ShareLinkExpiredError,
    ShareLinkStore,
    is_expired,
)

router = APIRouter()

WORKSPACE_OWNER_ROLES = {"ADMIN", "OWNER"}


def _extract_roles(request: Request) -> set[str]:
    secret = _get_jwt_secret()
    auth_header = request.headers.get("Authorization", "")
    if secret:
        if not auth_header.startswith("Bearer "):
            return set()
        try:
            payload = jwt.decode(
                auth_header[len("Bearer "):], secret, algorithms=["HS256", "HS384"]
            )
        except jwt.PyJWTError:
            return set()
        roles = payload.get("roles") or payload.get("role") or []
        if isinstance(roles, str):
            roles = [roles]
    else:
        roles = request.headers.get("X-User-Roles", "").split(",")
    return {str(r).strip().upper().removeprefix("ROLE_") for r in roles if str(r).strip()}


def _require_workspace_owner(request: Request) -> UUID:
    user_id = _require_user_id(request)
    if not _extract_roles(request) & WORKSPACE_OWNER_ROLES:
        raise HTTPException(
            status_code=403, detail="Only workspace owners can change the share policy"
        )
    return user_id


def link_response(link: ShareLink) -> ShareLinkResponse:
    response = ShareLinkResponse.model_validate(link)
    response.expired = is_expired(link)
    return response


async def _owned_document(document_id: UUID, user_id: UUID, db: AsyncSession) -> None:
    document = await DocumentService(db).get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_owner(document, user_id)


@router.get("/share-policy", response_model=SharePolicyResponse)
async def get_share_policy(request: Request, db: AsyncSession = Depends(get_db)):
    """Return the workspace default expiry and the allowed per-link bounds."""
    _require_user_id(request)
    return await ShareLinkStore(db).get_policy()


@router.put("/share-policy", response_model=SharePolicyResponse)
async def update_share_policy(
    body: SharePolicyUpdate, request: Request, db: AsyncSession = Depends(get_db)
):
    """Set the workspace default expiry and bounds. Applies to new links only."""
    actor_id = _require_workspace_owner(request)
    try:
        return await ShareLinkStore(db).update_policy(
            actor_id, body.default_expiry_days, body.min_expiry_days, body.max_expiry_days
        )
    except ExpiryOutOfBoundsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{document_id}/share-links", response_model=list[ShareLinkResponse])
async def list_share_links(
    document_id: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    user_id = _require_user_id(request)
    await _owned_document(document_id, user_id, db)
    return [link_response(link) for link in await ShareLinkStore(db).list_links(document_id)]


@router.patch(
    "/{document_id}/share-links/{link_id}", response_model=ShareLinkResponse
)
async def update_share_link_expiry(
    document_id: UUID,
    link_id: UUID,
    body: ShareLinkExpiryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Change a live link's expiry within the workspace bounds."""
    user_id = _require_user_id(request)
    await _owned_document(document_id, user_id, db)
    store = ShareLinkStore(db)
    link = await store.get_link(document_id, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    try:
        link = await store.update_expiry(link, user_id, body.expires_in_days)
    except ExpiryOutOfBoundsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ShareLinkExpiredError as exc:
        raise HTTPException(
            status_code=410, detail="Share link has expired; create a new link"
        ) from exc
    return link_response(link)
