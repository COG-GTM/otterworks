"""The OpenAPI schema documents every HTTPException status an endpoint can raise."""

import pytest
from httpx import AsyncClient

OWNER_CHECKED = {"401", "403", "404"}

EXPECTED_ERROR_RESPONSES = {
    ("/api/v1/documents/", "post"): {"401"},
    ("/api/v1/documents/", "get"): {"400"},
    ("/api/v1/documents/exports", "get"): {"404"},
    ("/api/v1/documents/shared", "get"): {"403", "404"},
    ("/api/v1/documents/{document_id}", "get"): OWNER_CHECKED,
    ("/api/v1/documents/{document_id}", "put"): OWNER_CHECKED,
    ("/api/v1/documents/{document_id}", "patch"): OWNER_CHECKED,
    ("/api/v1/documents/{document_id}", "delete"): OWNER_CHECKED,
    ("/api/v1/documents/{document_id}/versions", "get"): OWNER_CHECKED,
    (
        "/api/v1/documents/{document_id}/versions/{version_id}/restore",
        "post",
    ): OWNER_CHECKED,
    ("/api/v1/documents/{document_id}/share", "post"): OWNER_CHECKED,
    ("/api/v1/documents/{document_id}/export", "get"): OWNER_CHECKED,
    ("/api/v1/documents/from-template/{template_id}", "post"): {"404"},
    ("/api/v1/documents/{document_id}/comments", "post"): {"404"},
    ("/api/v1/documents/{document_id}/comments/{comment_id}", "delete"): {"404"},
}


@pytest.mark.asyncio
async def test_openapi_documents_http_exception_responses(client: AsyncClient):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]

    for (path, method), codes in EXPECTED_ERROR_RESPONSES.items():
        responses = paths[path][method]["responses"]
        missing = codes - responses.keys()
        assert not missing, f"{method.upper()} {path} does not document {sorted(missing)}"
        for code in codes:
            schema = responses[code]["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


@pytest.mark.asyncio
async def test_openapi_error_response_schema(client: AsyncClient):
    resp = await client.get("/openapi.json")
    schema = resp.json()["components"]["schemas"]["ErrorResponse"]
    assert schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["type"] == "string"
