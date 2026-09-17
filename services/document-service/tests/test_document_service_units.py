"""Unit tests for ``DocumentService`` branches that need a stubbed session."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.document_service as service_mod
from app.models.document import Document
from app.schemas.document import CommentCreate, DocumentPatch, DocumentUpdate
from app.services.document_service import DocumentService


@pytest.fixture
def publisher(monkeypatch) -> MagicMock:
    stub = MagicMock()
    stub.publish = AsyncMock()
    monkeypatch.setattr(service_mod, "event_publisher", stub)
    return stub


def _db(*scalar_results: object) -> MagicMock:
    """Session stub whose successive ``execute`` calls return the given scalars."""
    db = MagicMock()
    results = []
    for scalar in scalar_results:
        result = MagicMock()
        result.scalar_one_or_none.return_value = scalar
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return db


def _document(**overrides) -> Document:
    fields = {
        "id": uuid.uuid4(),
        "title": "Original",
        "content": "one two three",
        "content_type": "text/markdown",
        "owner_id": uuid.uuid4(),
        "folder_id": None,
        "word_count": 3,
        "version": 1,
    }
    fields.update(overrides)
    return Document(**fields)


@pytest.mark.asyncio
async def test_update_returns_none_for_an_unknown_document(publisher):
    service = DocumentService(_db(None))

    assert await service.update(uuid.uuid4(), DocumentUpdate(title="New")) is None
    publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_returns_none_for_an_unknown_document(publisher):
    service = DocumentService(_db(None))

    assert await service.patch(uuid.uuid4(), DocumentPatch(title="New")) is None
    publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_content_recomputes_the_word_count_and_bumps_the_version(publisher):
    document = _document()
    service = DocumentService(_db(document))

    result = await service.patch(document.id, DocumentPatch(content="four little words here"))

    assert result.content == "four little words here"
    assert result.word_count == 4
    assert result.version == 2
    assert publisher.publish.await_args.args[0] == "document_updated"


@pytest.mark.asyncio
async def test_patch_empty_content_zeroes_the_word_count(publisher):
    document = _document()
    service = DocumentService(_db(document))

    result = await service.patch(document.id, DocumentPatch(content=""))

    assert result.content == ""
    assert result.word_count == 0


@pytest.mark.asyncio
async def test_patch_content_type_and_folder_are_applied(publisher):
    document = _document()
    folder_id = uuid.uuid4()
    service = DocumentService(_db(document))

    result = await service.patch(
        document.id, DocumentPatch(content_type="text/html", folder_id=folder_id)
    )

    assert result.content_type == "text/html"
    assert result.folder_id == folder_id
    assert result.version == 2


@pytest.mark.asyncio
async def test_patch_without_any_field_leaves_the_version_untouched(publisher):
    document = _document()
    service = DocumentService(_db(document))

    result = await service.patch(document.id, DocumentPatch())

    assert result.version == 1
    publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_returns_false_for_an_unknown_document(publisher):
    service = DocumentService(_db(None))

    assert await service.delete(uuid.uuid4()) is False
    publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_version_returns_none_for_an_unknown_document(publisher):
    service = DocumentService(_db(None))

    assert await service.restore_version(uuid.uuid4(), uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_restore_version_returns_none_for_an_unknown_version(publisher):
    document = _document()
    service = DocumentService(_db(document, None))

    assert await service.restore_version(document.id, uuid.uuid4()) is None
    assert document.version == 1
    publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_comment_returns_false_for_an_unknown_comment():
    db = _db(None)
    service = DocumentService(db)

    assert await service.delete_comment(uuid.uuid4(), uuid.uuid4()) is False
    db.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_comment_returns_none_for_an_unknown_document(publisher):
    service = DocumentService(_db(None))

    body = CommentCreate(author_id=uuid.uuid4(), content="Hi")
    assert await service.add_comment(uuid.uuid4(), body) is None
    publisher.publish.assert_not_awaited()


@pytest.mark.parametrize(
    ("total", "page", "size", "expected"),
    [(0, 1, 20, 1), (1, 1, 20, 1), (41, 1, 20, 3), (10, 1, 0, 1)],
)
def test_paginate_never_returns_fewer_than_one_page(total, page, size, expected):
    assert DocumentService.paginate(total, page, size) == expected
