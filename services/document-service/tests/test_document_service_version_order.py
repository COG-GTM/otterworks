"""Ordering contract for DocumentService.list_versions.

Regression guard for df13716, which flipped this query from desc() to asc().
"""

import uuid

import pytest
from sqlalchemy import event
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


@pytest.mark.asyncio
async def test_list_documents_loads_recent_versions_in_one_query(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    """recent_versions is the newest five per document, fetched in one batch."""
    service = DocumentService(db_session)
    edited = await service.create(
        DocumentCreate(title="E1", content="e", owner_id=owner_id)
    )
    for n in range(2, 9):
        await service.update(edited.id, DocumentUpdate(title=f"E{n}", content=str(n)))
    single = await service.create(
        DocumentCreate(title="S1", content="s", owner_id=owner_id)
    )

    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", record)
    try:
        documents, total = await service.list_documents(owner_id=owner_id)
    finally:
        event.remove(sync_engine, "before_cursor_execute", record)

    assert total == 2
    by_id = {doc.id: doc for doc in documents}
    for doc_id in (edited.id, single.id):
        expected = [v.id for v in (await service.list_versions(doc_id))[:5]]
        assert [v.id for v in by_id[doc_id].recent_versions] == expected
    assert [v.version_number for v in by_id[edited.id].recent_versions] == [8, 7, 6, 5, 4]
    assert len(by_id[single.id].recent_versions) == 1
    version_queries = [
        s for s in statements if "row_number" in s.lower() and "document_versions" in s
    ]
    assert len(version_queries) == 1


@pytest.mark.asyncio
async def test_list_documents_empty_page_skips_version_query(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    documents, total = await DocumentService(db_session).list_documents(
        owner_id=owner_id
    )
    assert documents == [] and total == 0
