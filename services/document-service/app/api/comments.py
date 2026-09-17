"""Comment API endpoints."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.document import CommentCreate, CommentResolve, CommentResponse
from app.services.document_service import DocumentService

logger = structlog.get_logger()
router = APIRouter()


@router.post(
    "/{document_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    document_id: UUID,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a comment to a document."""
    service = DocumentService(db)
    comment = await service.add_comment(document_id, body)
    if not comment:
        raise HTTPException(status_code=404, detail="Document not found")
    logger.info("comment_added", document_id=str(document_id), comment_id=str(comment.id))
    return comment


@router.get("/{document_id}/comments", response_model=list[CommentResponse])
async def list_comments(
    document_id: UUID,
    include_resolved: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """List comments for a document."""
    service = DocumentService(db)
    return await service.list_comments(
        document_id, include_resolved=include_resolved
    )


@router.post(
    "/{document_id}/comments/{comment_id}/resolve",
    response_model=CommentResponse,
)
async def resolve_comment(
    document_id: UUID,
    comment_id: UUID,
    body: CommentResolve,
    db: AsyncSession = Depends(get_db),
):
    """Mark a comment as resolved."""
    service = DocumentService(db)
    comment = await service.resolve_comment(document_id, comment_id, body.resolved_by)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    logger.info(
        "comment_resolved", document_id=str(document_id), comment_id=str(comment_id)
    )
    return comment


@router.post(
    "/{document_id}/comments/{comment_id}/unresolve",
    response_model=CommentResponse,
)
async def unresolve_comment(
    document_id: UUID,
    comment_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark a comment as unresolved."""
    service = DocumentService(db)
    comment = await service.unresolve_comment(document_id, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    logger.info(
        "comment_unresolved", document_id=str(document_id), comment_id=str(comment_id)
    )
    return comment


@router.delete(
    "/{document_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment(
    document_id: UUID,
    comment_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a comment."""
    service = DocumentService(db)
    deleted = await service.delete_comment(document_id, comment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
    logger.info(
        "comment_deleted", document_id=str(document_id), comment_id=str(comment_id)
    )
