"""Ordering contract for DocumentService.list_versions.

Regression guard for df13716, which flipped this query from desc() to asc().
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.document import DocumentCreate, DocumentUpdate
from app.services.document_service import DocumentService


@pytest.mark.asyncio
async def test_list_versions_returns_newest_first(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="V1", content="first", owner_id=owner_id)
    )
    await service.update(doc.id, DocumentUpdate(title="V2", content="second"))
    await service.update(doc.id, DocumentUpdate(title="V3", content="third"))

    versions = await service.list_versions(doc.id)

    assert [v.version_number for v in versions] == [3, 2, 1]
    assert versions[0].title == "V3"


@pytest.mark.asyncio
async def test_list_versions_matches_recent_versions_ordering(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    """list_documents' recent_versions and list_versions must agree."""
    service = DocumentService(db_session)
    doc = await service.create(
        DocumentCreate(title="V1", content="first", owner_id=owner_id)
    )
    await service.update(doc.id, DocumentUpdate(title="V2", content="second"))

    documents, _ = await service.list_documents(owner_id=owner_id)
    versions = await service.list_versions(doc.id)

    assert [v.version_number for v in documents[0].recent_versions] == [
        v.version_number for v in versions
    ]
