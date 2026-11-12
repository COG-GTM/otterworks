"""Every HTTPException an endpoint raises is documented in its OpenAPI responses."""

import pytest

from app.main import app

EXPECTED_ERROR_RESPONSES = {
    ("/api/v1/documents/", "post"): {"401"},
    ("/api/v1/documents/", "get"): {"400"},
    ("/api/v1/documents/exports", "get"): {"404"},
    ("/api/v1/documents/shared", "get"): {"403", "404"},
    ("/api/v1/documents/{document_id}", "get"): {"401", "403", "404"},
    ("/api/v1/documents/{document_id}", "put"): {"401", "403", "404"},
    ("/api/v1/documents/{document_id}", "patch"): {"401", "403", "404"},
    ("/api/v1/documents/{document_id}", "delete"): {"401", "403", "404"},
    ("/api/v1/documents/{document_id}/versions", "get"): {"401", "403", "404"},
    ("/api/v1/documents/{document_id}/versions/{version_id}/restore", "post"): {
        "401",
        "403",
        "404",
    },
    ("/api/v1/documents/{document_id}/share", "post"): {"401", "403", "404"},
    ("/api/v1/documents/{document_id}/export", "get"): {"401", "403", "404"},
    ("/api/v1/documents/from-template/{template_id}", "post"): {"404"},
    ("/api/v1/documents/{document_id}/comments", "post"): {"404"},
    ("/api/v1/documents/{document_id}/comments/{comment_id}", "delete"): {"404"},
}


@pytest.mark.parametrize(("path", "method"), sorted(EXPECTED_ERROR_RESPONSES))
def test_error_responses_documented(path: str, method: str):
    responses = app.openapi()["paths"][path][method]["responses"]
    for code in EXPECTED_ERROR_RESPONSES[(path, method)]:
        assert code in responses, f"{method.upper()} {path} does not document {code}"
        assert list(responses[code]["content"]) == ["application/json"]
        schema = responses[code]["content"]["application/json"]["schema"]
        assert schema["required"] == ["detail"]
        assert schema["properties"]["detail"]["type"] == "string"
