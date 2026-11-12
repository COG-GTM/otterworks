"""Every HTTPException an endpoint raises is documented in its OpenAPI responses."""

import ast
import inspect
import textwrap

import pytest
from fastapi.routing import APIRoute

from app.main import app

ERROR_SCHEMA_REF = "#/components/schemas/ErrorResponse"

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
    ("post", "/api/v1/documents/{document_id}/versions/{version_id}/restore"): {
        "401",
        "403",
        "404",
    },
    ("post", "/api/v1/documents/{document_id}/share"): {"401", "403", "404"},
    ("get", "/api/v1/documents/{document_id}/export"): {"401", "403", "404"},
    ("post", "/api/v1/documents/from-template/{template_id}"): {"404"},
    ("post", "/api/v1/documents/{document_id}/comments"): {"404"},
    ("delete", "/api/v1/documents/{document_id}/comments/{comment_id}"): {"404"},
}


def _raised_status_codes(endpoint) -> set[int]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    codes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException":
            for kw in node.keywords:
                if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
                    codes.add(kw.value.value)
    return codes


@pytest.mark.parametrize(("method", "path"), sorted(EXPECTED_ERROR_RESPONSES))
def test_openapi_documents_error_responses(method, path):
    operation = app.openapi()["paths"][path][method]
    for code in EXPECTED_ERROR_RESPONSES[(method, path)]:
        response = operation["responses"].get(code)
        assert response, f"{method.upper()} {path} does not document {code}"
        assert response["description"]
        assert set(response["content"]) == {"application/json"}
        schema = response["content"]["application/json"]["schema"]
        if "$ref" in schema:
            assert schema == {"$ref": ERROR_SCHEMA_REF}
        else:
            assert schema["required"] == ["detail"]


def test_error_response_schema_is_published():
    schema = app.openapi()["components"]["schemas"]["ErrorResponse"]
    assert schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["type"] == "string"


def test_every_route_documents_the_exceptions_it_raises():
    undocumented = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        missing = _raised_status_codes(route.endpoint) - set(route.responses)
        if missing:
            undocumented.append((sorted(route.methods), route.path, sorted(missing)))
    assert undocumented == []
