"""Comment API endpoints."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _ensure_owner, _require_user_id
from app.db.session import get_db
from app.models.document import Document
from app.schemas.document import CommentCreate, CommentResponse
from app.services.document_service import DocumentService

logger = structlog.get_logger()
router = APIRouter()


async def _get_document(service: DocumentService, document_id: UUID) -> Document:
    document = await service.get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post(
    "/{document_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    document_id: UUID,
    body: CommentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Add a comment to a document as the authenticated user."""
    user_id = _require_user_id(request)
    service = DocumentService(db)
    _ensure_owner(await _get_document(service, document_id), user_id)
    comment = await service.add_comment(document_id, body, author_id=user_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Document not found")
    logger.info("comment_added", document_id=str(document_id), comment_id=str(comment.id))
    return comment


@router.get("/{document_id}/comments", response_model=list[CommentResponse])
async def list_comments(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List comments for a document owned by the authenticated user."""
    user_id = _require_user_id(request)
    service = DocumentService(db)
    _ensure_owner(await _get_document(service, document_id), user_id)
    return await service.list_comments(document_id)


@router.delete(
    "/{document_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment(
    document_id: UUID,
    comment_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a comment; allowed for the comment author or the document owner."""
    user_id = _require_user_id(request)
    service = DocumentService(db)
    document = await _get_document(service, document_id)
    comment = await service.get_comment(document_id, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if user_id not in (comment.author_id, document.owner_id):
        raise HTTPException(status_code=403, detail="Access denied")
    await service.delete_comment(document_id, comment_id)
    logger.info(
        "comment_deleted", document_id=str(document_id), comment_id=str(comment_id)
    )
