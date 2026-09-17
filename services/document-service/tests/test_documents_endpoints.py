"""Unit tests for the ``app.api.documents`` endpoint handlers.

The handlers are called directly with a stubbed ``DocumentService`` so that routing,
authorisation and error mapping are exercised independently of the database.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import documents
from app.schemas.document import (
    DocumentCreate,
    DocumentFromTemplate,
    DocumentPatch,
    DocumentUpdate,
)

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105

_ASYNC_METHODS = (
    "create",
    "get",
    "list_documents",
    "search",
    "update",
    "patch",
    "delete",
    "list_versions",
    "restore_version",
    "create_from_template",
)


@pytest.fixture
def owner_request(owner_id: uuid.UUID) -> Request:
    token = jwt.encode({"user_id": str(owner_id)}, TEST_JWT_SECRET, algorithm="HS256")
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )


@pytest.fixture
def anonymous_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


@pytest.fixture
def service(monkeypatch) -> MagicMock:
    """Stub ``DocumentService`` and disable chaos latency injection."""
    svc = MagicMock()
    for name in _ASYNC_METHODS:
        setattr(svc, name, AsyncMock())
    svc.paginate.return_value = 1
    monkeypatch.setattr(documents, "DocumentService", lambda _db: svc)
    monkeypatch.setattr(documents, "_chaos_active", lambda key: False)
    return svc


@pytest.fixture
def db() -> MagicMock:
    return MagicMock()


def _document(owner_id: uuid.UUID, **overrides) -> SimpleNamespace:
    now = datetime.now(UTC)
    fields = {
        "id": uuid.uuid4(),
        "title": "Doc",
        "content": "Body",
        "content_type": "text/markdown",
        "owner_id": owner_id,
        "folder_id": None,
        "is_deleted": False,
        "is_template": False,
        "word_count": 1,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _version(document_id: uuid.UUID, owner_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        document_id=document_id,
        version_number=1,
        title="Doc",
        content="Body",
        created_by=owner_id,
        created_at=datetime.now(UTC),
    )


# ---- create ----


@pytest.mark.parametrize(
    "handler", [documents.create_document, documents.create_document_no_slash]
)
@pytest.mark.asyncio
async def test_create_returns_the_created_document(
    handler, service, db, anonymous_request, owner_id
):
    body = DocumentCreate(title="Plan", content="Body", owner_id=owner_id)
    service.create.return_value = _document(owner_id, title="Plan")

    result = await handler(body, anonymous_request, db)

    assert result is service.create.return_value
    service.create.assert_awaited_once_with(body)


@pytest.mark.asyncio
async def test_create_falls_back_to_the_authenticated_user_as_owner(
    service, db, owner_request, owner_id
):
    body = DocumentCreate(title="Plan")
    service.create.return_value = _document(owner_id, title="Plan")

    await documents.create_document(body, owner_request, db)

    assert service.create.await_args.args[0].owner_id == owner_id


@pytest.mark.asyncio
async def test_create_without_owner_or_credentials_raises_401(service, db, anonymous_request):
    with pytest.raises(HTTPException) as exc:
        await documents.create_document(DocumentCreate(title="Plan"), anonymous_request, db)

    assert exc.value.status_code == 401
    service.create.assert_not_awaited()


# ---- search / list ----


@pytest.mark.asyncio
async def test_search_wraps_results_in_a_paginated_response(service, db, owner_id):
    service.search.return_value = ([_document(owner_id, title="Match")], 1)
    service.paginate.return_value = 1

    result = await documents.search_documents(q="match", page=1, size=20, db=db)

    service.search.assert_awaited_once_with("match", page=1, size=20)
    assert [item.title for item in result.items] == ["Match"]
    assert (result.total, result.page, result.size, result.pages) == (1, 1, 20, 1)


@pytest.mark.parametrize(
    "handler", [documents.list_documents, documents.list_documents_no_slash]
)
@pytest.mark.asyncio
async def test_list_uses_the_explicit_owner_filter(
    handler, service, db, anonymous_request, owner_id, folder_id
):
    service.list_documents.return_value = ([_document(owner_id)], 3)
    service.paginate.return_value = 2

    result = await handler(anonymous_request, owner_id, folder_id, 2, 2, db)

    service.list_documents.assert_awaited_once_with(
        owner_id=owner_id, folder_id=folder_id, page=2, size=2
    )
    assert (result.total, result.page, result.size, result.pages) == (3, 2, 2, 2)


@pytest.mark.asyncio
async def test_list_defaults_the_owner_filter_to_the_authenticated_user(
    service, db, owner_request, owner_id
):
    service.list_documents.return_value = ([], 0)

    await documents.list_documents(owner_request, None, None, 1, 20, db)

    assert service.list_documents.await_args.kwargs["owner_id"] == owner_id


# ---- read / update / delete ----


@pytest.mark.asyncio
async def test_get_document_returns_the_owned_document(service, db, owner_request, owner_id):
    document = _document(owner_id)
    service.get.return_value = document

    assert await documents.get_document(document.id, owner_request, db) is document


@pytest.mark.asyncio
async def test_get_document_raises_404_when_missing(service, db, owner_request):
    service.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.get_document(uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_document_raises_403_for_another_users_document(service, db, owner_request):
    service.get.return_value = _document(uuid.uuid4())

    with pytest.raises(HTTPException) as exc:
        await documents.get_document(uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_document_replaces_the_document(service, db, owner_request, owner_id):
    document = _document(owner_id)
    service.get.return_value = document
    service.update.return_value = _document(owner_id, id=document.id, title="New", version=2)
    body = DocumentUpdate(title="New", content="New body")

    result = await documents.update_document(document.id, body, owner_request, db)

    service.update.assert_awaited_once_with(document.id, body)
    assert result.title == "New"


@pytest.mark.asyncio
async def test_update_document_raises_404_when_missing(service, db, owner_request):
    service.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.update_document(
            uuid.uuid4(), DocumentUpdate(title="New"), owner_request, db
        )

    assert exc.value.status_code == 404
    service.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_document_raises_403_for_another_users_document(service, db, owner_request):
    service.get.return_value = _document(uuid.uuid4())

    with pytest.raises(HTTPException) as exc:
        await documents.update_document(
            uuid.uuid4(), DocumentUpdate(title="New"), owner_request, db
        )

    assert exc.value.status_code == 403
    service.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_document_applies_the_partial_update(service, db, owner_request, owner_id):
    document = _document(owner_id)
    service.get.return_value = document
    service.patch.return_value = _document(owner_id, id=document.id, title="Patched", version=2)
    body = DocumentPatch(title="Patched")

    result = await documents.patch_document(document.id, body, owner_request, db)

    service.patch.assert_awaited_once_with(document.id, body)
    assert result.title == "Patched"


@pytest.mark.asyncio
async def test_patch_document_raises_404_when_missing(service, db, owner_request):
    service.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.patch_document(
            uuid.uuid4(), DocumentPatch(title="Patched"), owner_request, db
        )

    assert exc.value.status_code == 404
    service.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_document_raises_403_for_another_users_document(service, db, owner_request):
    service.get.return_value = _document(uuid.uuid4())

    with pytest.raises(HTTPException) as exc:
        await documents.patch_document(
            uuid.uuid4(), DocumentPatch(title="Patched"), owner_request, db
        )

    assert exc.value.status_code == 403
    service.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_document_deletes_the_owned_document(service, db, owner_request, owner_id):
    document = _document(owner_id)
    service.get.return_value = document

    assert await documents.delete_document(document.id, owner_request, db) is None
    service.delete.assert_awaited_once_with(document.id)


@pytest.mark.asyncio
async def test_delete_document_raises_404_when_missing(service, db, owner_request):
    service.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.delete_document(uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 404
    service.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_document_raises_403_for_another_users_document(service, db, owner_request):
    service.get.return_value = _document(uuid.uuid4())

    with pytest.raises(HTTPException) as exc:
        await documents.delete_document(uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 403
    service.delete.assert_not_awaited()


# ---- versions ----


@pytest.mark.asyncio
async def test_list_versions_returns_the_service_result(service, db, owner_request, owner_id):
    document = _document(owner_id)
    service.get.return_value = document
    service.list_versions.return_value = [_version(document.id, owner_id)]

    result = await documents.list_versions(document.id, owner_request, db)

    assert result is service.list_versions.return_value
    service.list_versions.assert_awaited_once_with(document.id)


@pytest.mark.asyncio
async def test_list_versions_raises_404_when_the_document_is_missing(service, db, owner_request):
    service.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.list_versions(uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 404
    service.list_versions.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_versions_raises_403_for_another_users_document(service, db, owner_request):
    service.get.return_value = _document(uuid.uuid4())

    with pytest.raises(HTTPException) as exc:
        await documents.list_versions(uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_restore_version_returns_the_restored_document(
    service, db, owner_request, owner_id
):
    document = _document(owner_id)
    version_id = uuid.uuid4()
    service.get.return_value = document
    service.restore_version.return_value = _document(owner_id, id=document.id, version=3)

    result = await documents.restore_version(document.id, version_id, owner_request, db)

    service.restore_version.assert_awaited_once_with(document.id, version_id)
    assert result.version == 3


@pytest.mark.asyncio
async def test_restore_version_raises_404_when_the_document_is_missing(
    service, db, owner_request
):
    service.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.restore_version(uuid.uuid4(), uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 404
    service.restore_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_version_raises_404_when_the_version_is_missing(
    service, db, owner_request, owner_id
):
    service.get.return_value = _document(owner_id)
    service.restore_version.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.restore_version(uuid.uuid4(), uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document or version not found"


@pytest.mark.asyncio
async def test_restore_version_raises_403_for_another_users_document(service, db, owner_request):
    service.get.return_value = _document(uuid.uuid4())

    with pytest.raises(HTTPException) as exc:
        await documents.restore_version(uuid.uuid4(), uuid.uuid4(), owner_request, db)

    assert exc.value.status_code == 403
    service.restore_version.assert_not_awaited()


# ---- export / templates ----


@pytest.mark.asyncio
async def test_export_document_returns_the_rendered_body(service, db, owner_request, owner_id):
    document = _document(owner_id)
    service.get.return_value = document
    service.export_document.return_value = ("# Doc\n\nBody", "text/markdown")

    response = await documents.export_document(document.id, owner_request, "markdown", db)

    service.export_document.assert_called_once_with(document, "markdown")
    assert response.body == b"# Doc\n\nBody"
    assert response.media_type == "text/markdown"


@pytest.mark.asyncio
async def test_export_document_raises_404_when_missing(service, db, owner_request):
    service.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.export_document(uuid.uuid4(), owner_request, "html", db)

    assert exc.value.status_code == 404
    service.export_document.assert_not_called()


@pytest.mark.asyncio
async def test_export_document_raises_403_for_another_users_document(service, db, owner_request):
    service.get.return_value = _document(uuid.uuid4())

    with pytest.raises(HTTPException) as exc:
        await documents.export_document(uuid.uuid4(), owner_request, "html", db)

    assert exc.value.status_code == 403
    service.export_document.assert_not_called()


@pytest.mark.asyncio
async def test_create_from_template_returns_the_new_document(service, db, owner_id):
    template_id = uuid.uuid4()
    body = DocumentFromTemplate(title="From Template", owner_id=owner_id)
    service.create_from_template.return_value = _document(owner_id, title="From Template")

    result = await documents.create_from_template(template_id, body, db)

    service.create_from_template.assert_awaited_once_with(template_id, body)
    assert result.title == "From Template"


@pytest.mark.asyncio
async def test_create_from_template_raises_404_for_an_unknown_template(service, db, owner_id):
    service.create_from_template.return_value = None

    with pytest.raises(HTTPException) as exc:
        await documents.create_from_template(
            uuid.uuid4(), DocumentFromTemplate(title="Orphan", owner_id=owner_id), db
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Template not found"
