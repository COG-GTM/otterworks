"""Missing-document guards on DocumentService.

The HTTP layer 404s before reaching these branches, so they are exercised directly.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.document import DocumentPatch, DocumentUpdate
from app.services.document_service import DocumentService


async def test_update_returns_none_for_unknown_document(db_session: AsyncSession):
    service = DocumentService(db_session)

    assert await service.update(uuid.uuid4(), DocumentUpdate(title="Ghost")) is None


async def test_patch_returns_none_for_unknown_document(db_session: AsyncSession):
    service = DocumentService(db_session)

    assert await service.patch(uuid.uuid4(), DocumentPatch(title="Ghost")) is None


async def test_restore_version_returns_none_for_unknown_document(db_session: AsyncSession):
    service = DocumentService(db_session)

    assert await service.restore_version(uuid.uuid4(), uuid.uuid4()) is None


async def test_update_records_the_editor_when_supplied(db_session: AsyncSession, owner_id):
    from app.schemas.document import DocumentCreate

    service = DocumentService(db_session)
    doc = await service.create(DocumentCreate(title="Shared", content="v1", owner_id=owner_id))
    editor = uuid.uuid4()

    await service.update(doc.id, DocumentUpdate(title="Shared", content="v2"), updated_by=editor)

    versions = {v.version_number: v for v in await service.list_versions(doc.id)}
    assert versions[2].created_by == editor


async def test_patch_clearing_content_resets_the_word_count(db_session: AsyncSession, owner_id):
    from app.schemas.document import DocumentCreate

    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="Wordy", content="one two three", owner_id=owner_id)
    )

    patched = await service.patch(doc.id, DocumentPatch(content=""))

    assert patched is not None
    assert patched.word_count == 0
