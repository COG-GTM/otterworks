"""OpenAPI metadata for the HTTPException responses raised by the API routes."""

from typing import Any

from app.schemas.document import ErrorResponse


def _error(description: str) -> dict[str, Any]:
    return {"model": ErrorResponse, "description": description}


def _json_error(description: str) -> dict[str, Any]:
    """For routes with a non-JSON response_class, whose media type `model` would adopt."""
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
    }


INVALID_FILTER = _error("Invalid document filter")
AUTHENTICATION_REQUIRED = _error("Authentication required")
ACCESS_DENIED = _error("Caller does not own the document")
INVALID_SHARE_TOKEN = _error("Invalid share token")
DOCUMENT_NOT_FOUND = _error("Document not found")
VERSION_NOT_FOUND = _error("Document or version not found")
EXPORT_NOT_FOUND = _json_error("Export not found")
TEMPLATE_NOT_FOUND = _error("Template not found")
COMMENT_NOT_FOUND = _error("Comment not found")
