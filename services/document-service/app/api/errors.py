"""OpenAPI documentation for the HTTPException responses raised by the API."""

from typing import Any

from app.schemas.document import ErrorResponse

_DESCRIPTIONS = {
    400: "Invalid request parameters",
    401: "Authentication required",
    403: "Access denied",
    404: "Resource not found",
}

# HTTPException bodies are always JSON, even on routes whose success response is plain text,
# so the media type is set explicitly instead of letting FastAPI reuse the route's.
_ERROR_CONTENT = {"application/json": {"schema": ErrorResponse.model_json_schema()}}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Build a FastAPI ``responses`` mapping for the given error status codes."""
    return {
        code: {"description": _DESCRIPTIONS[code], "content": _ERROR_CONTENT}
        for code in status_codes
    }
