"""Every HTTPException an endpoint raises must be documented in its OpenAPI responses."""

import ast
import inspect
import textwrap

import pytest
from fastapi.routing import APIRoute

from app.api import comments, documents, templates
from app.main import app


def _raised_status_codes(endpoint) -> set[int]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    codes: set[int] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
            continue
        func = node.exc.func
        if getattr(func, "id", getattr(func, "attr", None)) != "HTTPException":
            continue
        for kw in node.exc.keywords:
            if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
                codes.add(kw.value.value)
    return codes


ROUTES = [
    route
    for router in (documents.router, comments.router, templates.router)
    for route in router.routes
    if isinstance(route, APIRoute)
]


@pytest.mark.parametrize(
    "route", ROUTES, ids=[f"{r.endpoint.__module__}:{r.endpoint.__name__}" for r in ROUTES]
)
def test_raised_http_exceptions_are_documented(route: APIRoute):
    documented = {int(code) for code in route.responses}
    assert _raised_status_codes(route.endpoint) <= documented


@pytest.mark.parametrize(
    ("path", "method", "codes"),
    [
        ("/api/v1/documents/{document_id}", "get", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}", "delete", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}/versions", "get", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}/share", "post", {"401", "403", "404"}),
        ("/api/v1/documents/shared", "get", {"403", "404"}),
        ("/api/v1/documents/exports", "get", {"404"}),
        ("/api/v1/documents/from-template/{template_id}", "post", {"404"}),
        ("/api/v1/documents/{document_id}/comments/{comment_id}", "delete", {"404"}),
    ],
)
def test_openapi_schema_lists_error_responses(path: str, method: str, codes: set[str]):
    responses = app.openapi()["paths"][path][method]["responses"]
    assert codes <= responses.keys()
