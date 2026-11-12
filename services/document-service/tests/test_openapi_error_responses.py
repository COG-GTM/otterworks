"""Every HTTPException a route can raise is documented in its OpenAPI responses."""

import ast
import inspect
import textwrap

import pytest
from fastapi.routing import APIRoute

from app.api import comments, documents
from app.main import app

ROUTERS = (documents.router, comments.router)

EXPECTED = {
    ("post", "/api/v1/documents/"): {401},
    ("get", "/api/v1/documents/"): {400},
    ("get", "/api/v1/documents/exports"): {404},
    ("get", "/api/v1/documents/shared"): {403, 404},
    ("get", "/api/v1/documents/{document_id}"): {401, 403, 404},
    ("put", "/api/v1/documents/{document_id}"): {401, 403, 404},
    ("patch", "/api/v1/documents/{document_id}"): {401, 403, 404},
    ("delete", "/api/v1/documents/{document_id}"): {401, 403, 404},
    ("get", "/api/v1/documents/{document_id}/versions"): {401, 403, 404},
    ("post", "/api/v1/documents/{document_id}/versions/{version_id}/restore"): {401, 403, 404},
    ("post", "/api/v1/documents/{document_id}/share"): {401, 403, 404},
    ("get", "/api/v1/documents/{document_id}/export"): {401, 403, 404},
    ("post", "/api/v1/documents/from-template/{template_id}"): {404},
    ("post", "/api/v1/documents/{document_id}/comments"): {404},
    ("delete", "/api/v1/documents/{document_id}/comments/{comment_id}"): {404},
}


def _raised_status_codes(func) -> set[int]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    codes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException":
            for kw in node.keywords:
                if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
                    codes.add(kw.value.value)
    return codes


@pytest.mark.parametrize(("method", "path"), sorted(EXPECTED))
def test_openapi_documents_error_responses(method: str, path: str):
    operation = app.openapi()["paths"][path][method]
    for code in EXPECTED[(method, path)]:
        response = operation["responses"][str(code)]
        assert response["description"]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_error_response_schema_matches_http_exception_body():
    schema = app.openapi()["components"]["schemas"]["ErrorResponse"]
    assert schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["type"] == "string"


@pytest.mark.parametrize(
    "route",
    [r for router in ROUTERS for r in router.routes if isinstance(r, APIRoute)],
    ids=lambda r: f"{sorted(r.methods)[0]} {r.path or '/'} ({r.name})",
)
def test_route_documents_every_status_code_it_raises(route: APIRoute):
    undocumented = _raised_status_codes(route.endpoint) - set(route.responses)
    assert not undocumented, f"{route.name} raises undocumented {sorted(undocumented)}"
