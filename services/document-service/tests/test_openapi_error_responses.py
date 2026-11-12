"""Every HTTPException an endpoint raises must be documented in its OpenAPI responses."""

import ast
import inspect
import textwrap

import pytest
from fastapi import status
from fastapi.routing import APIRoute

from app.api import comments, documents, templates
from app.main import app


def _status_code(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute) and getattr(node.value, "id", None) == "status":
        return getattr(status, node.attr, None)
    return None


def _raised_status_codes(func, seen: set | None = None) -> set[int]:
    """Statuses raised by ``func`` and by the same-module helpers it calls."""
    seen = set() if seen is None else seen
    if func in seen:
        return set()
    seen.add(func)
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    codes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            helper = func.__globals__.get(node.func.id)
            if inspect.isfunction(helper) and helper.__module__ == func.__module__:
                codes |= _raised_status_codes(helper, seen)
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
            continue
        exc = node.exc.func
        if getattr(exc, "id", getattr(exc, "attr", None)) != "HTTPException":
            continue
        for kw in node.exc.keywords:
            if kw.arg == "status_code" and (code := _status_code(kw.value)) is not None:
                codes.add(code)
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
        ("/api/v1/documents/", "post", {"401"}),
        ("/api/v1/documents/", "get", {"400"}),
        ("/api/v1/documents/{document_id}", "get", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}", "put", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}", "patch", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}", "delete", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}/versions", "get", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}/share", "post", {"401", "403", "404"}),
        ("/api/v1/documents/{document_id}/export", "get", {"401", "403", "404"}),
        (
            "/api/v1/documents/{document_id}/versions/{version_id}/restore",
            "post",
            {"401", "403", "404"},
        ),
        ("/api/v1/documents/shared", "get", {"403", "404"}),
        ("/api/v1/documents/exports", "get", {"404"}),
        ("/api/v1/documents/from-template/{template_id}", "post", {"404"}),
        ("/api/v1/documents/{document_id}/comments", "post", {"404"}),
        ("/api/v1/documents/{document_id}/comments/{comment_id}", "delete", {"404"}),
    ],
)
def test_openapi_schema_lists_error_responses(path: str, method: str, codes: set[str]):
    responses = app.openapi()["paths"][path][method]["responses"]
    assert codes <= responses.keys()
