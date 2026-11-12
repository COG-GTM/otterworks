"""The OpenAPI schema documents every HTTPException status a route can raise."""

import pytest

from app.main import app

AUTH_OWNED = {"401", "403", "404"}

EXPECTED_ERROR_RESPONSES = {
    ("/api/v1/documents/", "post"): {"401"},
    ("/api/v1/documents/", "get"): {"400"},
    ("/api/v1/documents/exports", "get"): {"404"},
    ("/api/v1/documents/shared", "get"): {"403", "404"},
    ("/api/v1/documents/{document_id}", "get"): AUTH_OWNED,
    ("/api/v1/documents/{document_id}", "put"): AUTH_OWNED,
    ("/api/v1/documents/{document_id}", "patch"): AUTH_OWNED,
    ("/api/v1/documents/{document_id}", "delete"): AUTH_OWNED,
    ("/api/v1/documents/{document_id}/versions", "get"): AUTH_OWNED,
    ("/api/v1/documents/{document_id}/versions/{version_id}/restore", "post"): AUTH_OWNED,
    ("/api/v1/documents/{document_id}/share", "post"): AUTH_OWNED,
    ("/api/v1/documents/{document_id}/export", "get"): AUTH_OWNED,
    ("/api/v1/documents/from-template/{template_id}", "post"): {"404"},
    ("/api/v1/documents/{document_id}/comments", "post"): {"404"},
    ("/api/v1/documents/{document_id}/comments/{comment_id}", "delete"): {"404"},
}


@pytest.mark.parametrize(("path", "method"), sorted(EXPECTED_ERROR_RESPONSES))
def test_route_documents_its_http_exceptions(path: str, method: str):
    responses = app.openapi()["paths"][path][method]["responses"]
    for code in EXPECTED_ERROR_RESPONSES[(path, method)]:
        assert code in responses, f"{method.upper()} {path} does not document {code}"
        schema = responses[code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
        assert responses[code]["description"]


def test_error_response_schema_matches_the_http_exception_body():
    schema = app.openapi()["components"]["schemas"]["ErrorResponse"]
    assert schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["type"] == "string"
