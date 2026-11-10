"""Health check and metrics endpoints."""

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.audit_client import emit_failures_total

logger = structlog.get_logger()
router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Health check with DB connectivity verification."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        logger.exception("health_check_db_failed")
        db_status = "disconnected"

    status = "healthy" if db_status == "connected" else "degraded"
    return {
        "status": status,
        "service": "document-service",
        "checks": {"database": db_status},
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint."""
    return (
        "# HELP document_service_up Document Service is running\n"
        "# TYPE document_service_up gauge\n"
        "document_service_up 1\n"
        "# HELP audit_emit_failures_total Audit events that could not be delivered\n"
        "# TYPE audit_emit_failures_total counter\n"
        f"audit_emit_failures_total {emit_failures_total()}\n"
    )
