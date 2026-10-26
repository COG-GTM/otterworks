"""Template API endpoints."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _caller_roles, _require_user_id
from app.db.session import get_db
from app.schemas.document import TemplateCreate, TemplateResponse
from app.services.document_service import DocumentService

logger = structlog.get_logger()
router = APIRouter()

# Templates are listed to every user, so only administrators may publish them.
TEMPLATE_AUTHOR_ROLES = frozenset({"ADMIN", "OWNER"})


@router.get("/", response_model=list[TemplateResponse])
async def list_templates(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List all templates."""
    _require_user_id(request)
    service = DocumentService(db)
    return await service.list_templates()


@router.post(
    "/", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED
)
async def create_template(
    body: TemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new template authored by the authenticated administrator."""
    user_id = _require_user_id(request)
    if not _caller_roles(request) & TEMPLATE_AUTHOR_ROLES:
        logger.warning("template_create_forbidden", user_id=str(user_id))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creating templates requires an administrator role",
        )
    service = DocumentService(db)
    template = await service.create_template(body, created_by=user_id)
    logger.info("template_created", template_id=str(template.id), created_by=str(user_id))
    return template
