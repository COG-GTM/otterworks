"""OpenAPI ``responses`` entries for the HTTPExceptions raised by the API routes."""

from typing import Any

from app.schemas.document import ErrorResponse


def _error(description: str) -> dict[str, Any]:
    return {"model": ErrorResponse, "description": description}


def _json_error(description: str) -> dict[str, Any]:
    """Error entry for routes whose success ``response_class`` is not JSON."""
    return {
        "description": description,
        "content": {"application/json": {"schema": ErrorResponse.model_json_schema()}},
    }


INVALID_FILTER = _error("Invalid filter or sort parameters")
AUTH_REQUIRED = _error("Authentication required")
OWNER_REQUIRED = _error("Authentication required (no owner_id and no valid JWT)")
ACCESS_DENIED = _error("Access denied (not the owner)")
INVALID_SHARE_TOKEN = _error("Invalid share token")
DOCUMENT_NOT_FOUND = _error("Document not found")
DOCUMENT_OR_VERSION_NOT_FOUND = _error("Document or version not found")
EXPORT_NOT_FOUND = _json_error("Export not found")
COMMENT_NOT_FOUND = _error("Comment not found")
TEMPLATE_NOT_FOUND = _error("Template not found")
