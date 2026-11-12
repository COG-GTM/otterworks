"""Every HTTPException an endpoint raises is documented in its OpenAPI responses."""

import pytest
from fastapi.routing import APIRoute

from app.api import comments, documents
from app.main import app

PREFIX = "/api/v1/documents"
OWNED = {"401", "403", "404"}

EXPECTED_ERRORS = {
    ("POST", f"{PREFIX}/"): {"401"},
    ("POST", PREFIX): {"401"},
    ("GET", f"{PREFIX}/exports"): {"404"},
    ("GET", f"{PREFIX}/shared"): {"403", "404"},
    ("GET", f"{PREFIX}/"): {"400"},
    ("GET", PREFIX): {"400"},
    ("GET", f"{PREFIX}/{{document_id}}"): OWNED,
    ("PUT", f"{PREFIX}/{{document_id}}"): OWNED,
    ("PATCH", f"{PREFIX}/{{document_id}}"): OWNED,
    ("DELETE", f"{PREFIX}/{{document_id}}"): OWNED,
    ("GET", f"{PREFIX}/{{document_id}}/versions"): OWNED,
    ("POST", f"{PREFIX}/{{document_id}}/versions/{{version_id}}/restore"): OWNED,
    ("POST", f"{PREFIX}/{{document_id}}/share"): OWNED,
    ("GET", f"{PREFIX}/{{document_id}}/export"): OWNED,
    ("POST", f"{PREFIX}/from-template/{{template_id}}"): {"404"},
    ("POST", f"{PREFIX}/{{document_id}}/comments"): {"404"},
    ("DELETE", f"{PREFIX}/{{document_id}}/comments/{{comment_id}}"): {"404"},
}


def _route_responses() -> dict[tuple[str, str], set[str]]:
    """Responses declared on each route, including ones hidden from the schema."""
    documented = {}
    for router in (documents.router, comments.router):
        for route in router.routes:
            if isinstance(route, APIRoute):
                for method in route.methods:
                    key = (method, PREFIX + route.path)
                    documented[key] = {str(code) for code in route.responses}
    return documented


@pytest.mark.parametrize(("method", "path"), sorted(EXPECTED_ERRORS))
def test_route_documents_raised_errors(method: str, path: str):
    documented = _route_responses()
    assert (method, path) in documented
    assert EXPECTED_ERRORS[(method, path)] <= documented[(method, path)]


@pytest.mark.parametrize(("method", "path"), sorted(EXPECTED_ERRORS))
def test_openapi_error_responses_use_error_schema(method: str, path: str):
    operation = app.openapi()["paths"].get(path, {}).get(method.lower())
    if operation is None:
        pytest.skip("route is excluded from the OpenAPI schema")
    for code in EXPECTED_ERRORS[(method, path)]:
        response = operation["responses"][code]
        assert response["description"]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_error_schema_matches_http_exception_body():
    schema = app.openapi()["components"]["schemas"]["ErrorResponse"]
    assert schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["type"] == "string"
