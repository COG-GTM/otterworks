"""Edge cases of DocumentService not exercised by the happy-path suite."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.document import DocumentCreate, DocumentPatch, DocumentUpdate
from app.services.document_service import DocumentService, _word_count


async def _create(service: DocumentService, owner_id: uuid.UUID) -> object:
    return await service.create(
        DocumentCreate(title="Original", content="one two three", owner_id=owner_id)
    )


@pytest.mark.parametrize(
    ("text", "expected"), [("", 0), ("   ", 0), ("one", 1), ("one two\nthree", 3)]
)
def test_word_count(text: str, expected: int):
    assert _word_count(text) == expected


@pytest.mark.asyncio
async def test_update_missing_document_returns_none(db_session: AsyncSession):
    service = DocumentService(db_session)

    result = await service.update(
        uuid.uuid4(), DocumentUpdate(title="Ghost", content="Body")
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
        document.id, DocumentUpdate(title="Edited", content="new body"), updated_by=editor_id
    )

    versions = await service.list_versions(document.id)
    assert versions[0].version_number == 2
    assert versions[0].created_by == editor_id


@pytest.mark.asyncio
async def test_patch_missing_document_returns_none(db_session: AsyncSession):
    service = DocumentService(db_session)

    result = await service.patch(uuid.uuid4(), DocumentPatch(title="Ghost"))

    assert result is None


@pytest.mark.asyncio
async def test_patch_without_any_field_leaves_the_document_untouched(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    patched = await service.patch(document.id, DocumentPatch())

    assert patched.version == 1
    assert patched.title == "Original"
    assert len(await service.list_versions(document.id)) == 1


@pytest.mark.asyncio
async def test_patch_content_recomputes_the_word_count(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    patched = await service.patch(document.id, DocumentPatch(content="four five"))

    assert patched.content == "four five"
    assert patched.word_count == 2
    assert patched.version == 2


@pytest.mark.asyncio
async def test_patch_empty_content_zeroes_the_word_count(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    patched = await service.patch(document.id, DocumentPatch(content=""))

    assert patched.content == ""
    assert patched.word_count == 0


@pytest.mark.asyncio
async def test_patch_content_type_and_folder(
    db_session: AsyncSession, owner_id: uuid.UUID, folder_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)

    patched = await service.patch(
        document.id, DocumentPatch(content_type="text/html", folder_id=folder_id)
    )

    assert patched.content_type == "text/html"
    assert patched.folder_id == folder_id
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
async def test_restore_version_from_another_document_is_rejected(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    mine = await _create(service, owner_id)
    theirs = await service.create(
        DocumentCreate(title="Theirs", content="body", owner_id=uuid.uuid4())
    )
    foreign_version = (await service.list_versions(theirs.id))[0]

    assert await service.restore_version(mine.id, foreign_version.id) is None


@pytest.mark.asyncio
async def test_search_escapes_like_wildcards(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    """A wildcard in the query must not widen the match set.

    ``search`` backslash-escapes ``%``/``_``/``\\`` but issues the ILIKE without an
    ESCAPE clause, so what the escape means is engine-dependent: PostgreSQL treats a
    backslash as the default escape character and matches the literal ``%``, while
    SQLite (used here) has no default escape character and matches nothing at all.
    Either way no unrelated document may come back.
    """
    service = DocumentService(db_session)
    await service.create(
        DocumentCreate(title="100% cotton", content="body", owner_id=owner_id)
    )
    await service.create(
        DocumentCreate(title="anything else", content="body", owner_id=owner_id)
    )

    matches, total = await service.search("%")

    assert total == len(matches)
    assert "anything else" not in [doc.title for doc in matches]


@pytest.mark.asyncio
async def test_search_skips_deleted_documents(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await service.create(
        DocumentCreate(title="Quarterly plan", content="body", owner_id=owner_id)
    )
    await service.delete(document.id)

    matches, total = await service.search("Quarterly")

    assert (matches, total) == ([], 0)


@pytest.mark.asyncio
async def test_list_documents_attaches_the_five_most_recent_versions(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    document = await _create(service, owner_id)
    for revision in range(6):
        await service.update(
            document.id, DocumentUpdate(title=f"Revision {revision}", content="body")
        )

    documents, total = await service.list_documents(owner_id=owner_id)

    assert total == 1
    assert [v.version_number for v in documents[0].recent_versions] == [7, 6, 5, 4, 3]


@pytest.mark.asyncio
async def test_delete_comment_that_does_not_exist(db_session: AsyncSession):
    service = DocumentService(db_session)

    assert await service.delete_comment(uuid.uuid4(), uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_get_template_that_does_not_exist(db_session: AsyncSession):
    service = DocumentService(db_session)

    assert await service.get_template(uuid.uuid4()) is None


@pytest.mark.parametrize(
    ("total", "page", "size", "expected"),
    [(0, 1, 20, 1), (1, 1, 20, 1), (21, 1, 20, 2), (40, 2, 20, 2), (5, 1, 0, 1)],
)
def test_paginate(total: int, page: int, size: int, expected: int):
    assert DocumentService.paginate(total, page, size) == expected
