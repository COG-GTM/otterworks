"""Every HTTPException an endpoint raises is documented in its OpenAPI responses."""

import pytest

from app.main import app

EXPECTED_ERROR_RESPONSES = {
    ("post", "/api/v1/documents/"): {"401"},
    ("get", "/api/v1/documents/"): {"400"},
    ("get", "/api/v1/documents/exports"): {"404"},
    ("get", "/api/v1/documents/shared"): {"403", "404"},
    ("get", "/api/v1/documents/{document_id}"): {"401", "403", "404"},
    ("put", "/api/v1/documents/{document_id}"): {"401", "403", "404"},
    ("patch", "/api/v1/documents/{document_id}"): {"401", "403", "404"},
    ("delete", "/api/v1/documents/{document_id}"): {"401", "403", "404"},
    ("get", "/api/v1/documents/{document_id}/versions"): {"401", "403", "404"},
    (
        "post",
        "/api/v1/documents/{document_id}/versions/{version_id}/restore",
    ): {"401", "403", "404"},
    ("post", "/api/v1/documents/{document_id}/share"): {"401", "403", "404"},
    ("get", "/api/v1/documents/{document_id}/export"): {"401", "403", "404"},
    ("post", "/api/v1/documents/from-template/{template_id}"): {"404"},
    ("post", "/api/v1/documents/{document_id}/comments"): {"404"},
    ("delete", "/api/v1/documents/{document_id}/comments/{comment_id}"): {"404"},
}


@pytest.mark.parametrize(("method", "path"), sorted(EXPECTED_ERROR_RESPONSES), ids=lambda v: v)
def test_error_responses_documented(method: str, path: str):
    responses = app.openapi()["paths"][path][method]["responses"]
    missing = EXPECTED_ERROR_RESPONSES[(method, path)] - responses.keys()
    assert not missing, f"{method.upper()} {path} does not document {sorted(missing)}"
    for code in EXPECTED_ERROR_RESPONSES[(method, path)]:
        assert responses[code]["description"]
