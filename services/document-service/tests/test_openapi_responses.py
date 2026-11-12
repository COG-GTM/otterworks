"""Every HTTPException an endpoint raises is documented in its OpenAPI responses."""

import pytest
from fastapi.routing import APIRoute

from app.api import documents
from app.main import app

DOCS = "/api/v1/documents"
OWNED = {"401", "403", "404"}

DOCUMENTED_ERRORS = [
    ("post", f"{DOCS}/", {"401"}),
    ("get", f"{DOCS}/", {"400"}),
    ("get", f"{DOCS}/exports", {"404"}),
    ("get", f"{DOCS}/shared", {"403", "404"}),
    ("get", f"{DOCS}/{{document_id}}", OWNED),
    ("put", f"{DOCS}/{{document_id}}", OWNED),
    ("patch", f"{DOCS}/{{document_id}}", OWNED),
    ("delete", f"{DOCS}/{{document_id}}", OWNED),
    ("get", f"{DOCS}/{{document_id}}/versions", OWNED),
    ("post", f"{DOCS}/{{document_id}}/versions/{{version_id}}/restore", OWNED),
    ("post", f"{DOCS}/{{document_id}}/share", OWNED),
    ("get", f"{DOCS}/{{document_id}}/export", OWNED),
    ("post", f"{DOCS}/from-template/{{template_id}}", {"404"}),
    ("post", f"{DOCS}/{{document_id}}/comments", {"404"}),
    ("delete", f"{DOCS}/{{document_id}}/comments/{{comment_id}}", {"404"}),
]


@pytest.mark.parametrize(("method", "path", "codes"), DOCUMENTED_ERRORS)
def test_error_responses_documented_in_openapi(method: str, path: str, codes: set[str]):
    responses = app.openapi()["paths"][path][method]["responses"]
    assert codes <= responses.keys()
    for code in codes:
        assert responses[code]["description"]


@pytest.mark.parametrize(("method", "codes"), [("POST", {401}), ("GET", {400})])
def test_no_slash_aliases_document_same_errors(method: str, codes: set[int]):
    route = next(
        r
        for r in documents.router.routes
        if isinstance(r, APIRoute) and r.path == "" and method in r.methods
    )
    assert codes <= route.responses.keys()
