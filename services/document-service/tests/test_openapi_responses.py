"""Every HTTPException an endpoint raises must be documented in its OpenAPI responses."""

import pytest

from app.main import app

DOCS = "/api/v1/documents"

OWNED_DOCUMENT = {"401", "403", "404"}

EXPECTED_ERROR_RESPONSES = {
    ("post", f"{DOCS}/"): {"401"},
    ("get", f"{DOCS}/"): {"400"},
    ("get", f"{DOCS}/exports"): {"404"},
    ("get", f"{DOCS}/shared"): {"403", "404"},
    ("get", f"{DOCS}/{{document_id}}"): OWNED_DOCUMENT,
    ("put", f"{DOCS}/{{document_id}}"): OWNED_DOCUMENT,
    ("patch", f"{DOCS}/{{document_id}}"): OWNED_DOCUMENT,
    ("delete", f"{DOCS}/{{document_id}}"): OWNED_DOCUMENT,
    ("get", f"{DOCS}/{{document_id}}/versions"): OWNED_DOCUMENT,
    ("post", f"{DOCS}/{{document_id}}/versions/{{version_id}}/restore"): OWNED_DOCUMENT,
    ("post", f"{DOCS}/{{document_id}}/share"): OWNED_DOCUMENT,
    ("get", f"{DOCS}/{{document_id}}/export"): OWNED_DOCUMENT,
    ("post", f"{DOCS}/from-template/{{template_id}}"): {"404"},
    ("post", f"{DOCS}/{{document_id}}/comments"): {"404"},
    ("delete", f"{DOCS}/{{document_id}}/comments/{{comment_id}}"): {"404"},
}


@pytest.mark.parametrize(
    ("method", "path"),
    sorted(EXPECTED_ERROR_RESPONSES),
    ids=[f"{m.upper()} {p}" for m, p in sorted(EXPECTED_ERROR_RESPONSES)],
)
def test_error_responses_documented(method: str, path: str):
    responses = app.openapi()["paths"][path][method]["responses"]
    missing = EXPECTED_ERROR_RESPONSES[(method, path)] - responses.keys()
    assert not missing, f"{method.upper()} {path} does not document {sorted(missing)}"
    for code in EXPECTED_ERROR_RESPONSES[(method, path)]:
        assert responses[code]["description"]
