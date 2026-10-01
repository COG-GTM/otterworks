"""Edge cases of DocumentService: missing rows and selective patching."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.document import (
    CommentCreate,
    DocumentCreate,
    DocumentFromTemplate,
    DocumentPatch,
    DocumentUpdate,
)
from app.services.document_service import DocumentService, _word_count


async def _create(service: DocumentService, owner_id: uuid.UUID):
    return await service.create(
        DocumentCreate(title="Original", content="one two", owner_id=owner_id)
    )


@pytest.mark.parametrize(
    ("text", "expected"), [("", 0), ("one", 1), ("one two  three", 3)]
)
def test_word_count(text, expected):
    assert _word_count(text) == expected


@pytest.mark.asyncio
async def test_update_missing_document_returns_none(db_session: AsyncSession):
    service = DocumentService(db_session)

    result = await service.update(
        uuid.uuid4(), DocumentUpdate(title="T", content="c", content_type="text/plain")
    )

    assert result is None


@pytest.mark.asyncio
async def test_update_records_the_updating_user_on_the_version(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)
    editor_id = uuid.uuid4()

    await service.update(
        document.id,
        DocumentUpdate(title="Edited", content="a b c", content_type="text/plain"),
        updated_by=editor_id,
    )

    versions = await service.list_versions(document.id)
    assert versions[0].version_number == 2
    assert versions[0].created_by == editor_id


@pytest.mark.asyncio
async def test_patch_missing_document_returns_none(db_session: AsyncSession):
    service = DocumentService(db_session)

    assert await service.patch(uuid.uuid4(), DocumentPatch(title="T")) is None


@pytest.mark.asyncio
async def test_patch_without_fields_does_not_create_a_version(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    patched = await service.patch(document.id, DocumentPatch())

    assert patched.version == 1
    assert len(await service.list_versions(document.id)) == 1


@pytest.mark.asyncio
async def test_patch_content_type_and_folder_only(
    db_session: AsyncSession, owner_id: uuid.UUID, folder_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    patched = await service.patch(
        document.id, DocumentPatch(content_type="text/markdown", folder_id=folder_id)
    )

    assert patched.content_type == "text/markdown"
    assert patched.folder_id == folder_id
    assert patched.title == "Original"
    assert patched.version == 2


@pytest.mark.asyncio
async def test_patch_content_updates_word_count(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    patched = await service.patch(document.id, DocumentPatch(content="a b c d"))

    assert patched.word_count == 4
    assert patched.version == 2


@pytest.mark.asyncio
async def test_restore_version_of_missing_document_returns_none(db_session: AsyncSession):
    service = DocumentService(db_session)

    assert await service.restore_version(uuid.uuid4(), uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_restore_unknown_version_returns_none(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    assert await service.restore_version(document.id, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_delete_comment_of_unknown_comment_returns_false(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    assert await service.delete_comment(document.id, uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_delete_comment_scoped_to_its_document(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)
    other = await service.create(
        DocumentCreate(title="Other", content="x", owner_id=owner_id)
    )
    comment = await service.add_comment(
        document.id, CommentCreate(author_id=owner_id, content="hi")
    )

    assert await service.delete_comment(other.id, comment.id) is False
    assert await service.delete_comment(document.id, comment.id) is True
    assert await service.list_comments(document.id) == []


@pytest.mark.asyncio
async def test_add_comment_to_missing_document_returns_none(db_session: AsyncSession):
    service = DocumentService(db_session)

    result = await service.add_comment(
        uuid.uuid4(), CommentCreate(author_id=uuid.uuid4(), content="hi")
    )

    assert result is None


@pytest.mark.asyncio
async def test_create_from_missing_template_returns_none(db_session: AsyncSession):
    service = DocumentService(db_session)

    result = await service.create_from_template(
        uuid.uuid4(), DocumentFromTemplate(title="T", owner_id=uuid.uuid4())
    )

    assert result is None


@pytest.mark.asyncio
async def test_search_matches_content_case_insensitively(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    await service.create(
        DocumentCreate(
            title="Discount memo", content="Quarterly Revenue", owner_id=owner_id
        )
    )
    await service.create(
        DocumentCreate(title="Plain title", content="body", owner_id=owner_id)
    )

    matches, total = await service.search("quarterly")

    assert total == 1
    assert matches[0].title == "Discount memo"


@pytest.mark.asyncio
async def test_search_skips_deleted_documents(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await service.create(
        DocumentCreate(title="Archived plan", content="x", owner_id=owner_id)
    )
    await service.delete(document.id)

    matches, total = await service.search("Archived")

    assert (matches, total) == ([], 0)


@pytest.mark.asyncio
async def test_list_documents_filters_by_folder(
    db_session: AsyncSession, owner_id: uuid.UUID, folder_id: uuid.UUID
):
    service = DocumentService(db_session)
    await service.create(
        DocumentCreate(
            title="In folder", content="x", owner_id=owner_id, folder_id=folder_id
        )
    )
    await service.create(
        DocumentCreate(title="Loose", content="x", owner_id=owner_id)
    )

    items, total = await service.list_documents(owner_id=owner_id, folder_id=folder_id)

    assert total == 1
    assert items[0].title == "In folder"
    assert [v.version_number for v in items[0].recent_versions] == [1]


@pytest.mark.parametrize(
    ("total", "page", "size", "expected"),
    [(0, 1, 20, 1), (20, 1, 20, 1), (21, 1, 20, 2), (5, 1, 0, 1)],
)
def test_paginate(total, page, size, expected):
    assert DocumentService.paginate(total, page, size) == expected
