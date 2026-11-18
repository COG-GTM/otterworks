"""Service-layer edge cases: missing documents and per-field PATCH."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.document import DocumentCreate, DocumentPatch, DocumentUpdate
from app.services.document_service import DocumentService


async def _make(db: AsyncSession, owner_id: uuid.UUID, **kwargs):
    data = {"title": "Doc", "content": "one two", "owner_id": owner_id}
    data.update(kwargs)
    return await DocumentService(db).create(DocumentCreate(**data))


@pytest.mark.asyncio
async def test_mutations_on_missing_document_return_none(db_session: AsyncSession):
    service = DocumentService(db_session)
    missing = uuid.uuid4()
    assert await service.update(missing, DocumentUpdate(title="x")) is None
    assert await service.patch(missing, DocumentPatch(title="x")) is None
    assert await service.restore_version(missing, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_restore_unknown_version_returns_none(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    doc = await _make(db_session, owner_id)
    service = DocumentService(db_session)
    assert await service.restore_version(doc.id, uuid.uuid4()) is None
    assert (await service.get(doc.id)).version == 1


@pytest.mark.asyncio
async def test_update_records_explicit_editor(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    doc = await _make(db_session, owner_id)
    editor = uuid.uuid4()
    service = DocumentService(db_session)
    await service.update(doc.id, DocumentUpdate(title="New", content="a"), updated_by=editor)
    versions = await service.list_versions(doc.id)
    assert versions[0].created_by == editor


@pytest.mark.asyncio
async def test_patch_content_only(db_session: AsyncSession, owner_id: uuid.UUID):
    doc = await _make(db_session, owner_id)
    patched = await DocumentService(db_session).patch(
        doc.id, DocumentPatch(content="alpha beta gamma")
    )
    assert patched.title == "Doc"
    assert patched.content == "alpha beta gamma"
    assert patched.word_count == 3
    assert patched.version == 2


@pytest.mark.asyncio
async def test_patch_content_to_empty_resets_word_count(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    doc = await _make(db_session, owner_id)
    patched = await DocumentService(db_session).patch(doc.id, DocumentPatch(content=""))
    assert patched.content == ""
    assert patched.word_count == 0


@pytest.mark.asyncio
async def test_patch_content_type_and_folder(
    db_session: AsyncSession, owner_id: uuid.UUID, folder_id: uuid.UUID
):
    doc = await _make(db_session, owner_id)
    service = DocumentService(db_session)
    patched = await service.patch(doc.id, DocumentPatch(content_type="text/html"))
    assert patched.content_type == "text/html"
    assert patched.version == 2

    patched = await service.patch(doc.id, DocumentPatch(folder_id=folder_id))
    assert patched.folder_id == folder_id
    assert patched.version == 3
    assert len(await service.list_versions(doc.id)) == 3


@pytest.mark.asyncio
async def test_patch_with_no_fields_does_not_bump_version(
    db_session: AsyncSession, owner_id: uuid.UUID, monkeypatch
):
    doc = await _make(db_session, owner_id)
    published = []

    async def _publish(event_type, payload):
        published.append(event_type)

    monkeypatch.setattr(
        "app.services.document_service.event_publisher.publish", _publish
    )
    patched = await DocumentService(db_session).patch(doc.id, DocumentPatch())
    assert patched.version == 1
    assert len(await DocumentService(db_session).list_versions(doc.id)) == 1
    assert published == []


@pytest.mark.asyncio
async def test_patch_rejects_explicit_null_for_required_fields():
    for field in ("title", "content", "content_type"):
        with pytest.raises(ValueError, match=f"{field} cannot be null"):
            DocumentPatch(**{field: None})
    assert DocumentPatch(folder_id=None).folder_id is None


@pytest.mark.asyncio
async def test_patch_null_title_via_api_returns_422(
    client, owner_id: uuid.UUID
):
    resp = await client.post(
        "/api/v1/documents/", json={"title": "Doc", "owner_id": str(owner_id)}
    )
    doc_id = resp.json()["id"]
    resp = await client.patch(f"/api/v1/documents/{doc_id}", json={"title": None})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_mutations_publish_index_events(
    db_session: AsyncSession, owner_id: uuid.UUID, monkeypatch
):
    published: list[tuple[str, dict]] = []

    async def _publish(event_type, payload):
        published.append((event_type, payload))

    monkeypatch.setattr(
        "app.services.document_service.event_publisher.publish", _publish
    )
    service = DocumentService(db_session)
    doc = await _make(db_session, owner_id)
    await service.patch(doc.id, DocumentPatch(title="Renamed"))
    first_version = (await service.list_versions(doc.id))[-1]
    await service.restore_version(doc.id, first_version.id)
    await service.delete(doc.id)

    assert [e for e, _ in published] == [
        "document_created",
        "document_updated",
        "document_updated",
        "document_deleted",
    ]
    assert published[0][1]["id"] == doc.id
    assert published[0][1]["owner_id"] == owner_id
    assert published[2][1]["restored_from"] == first_version.id
    assert published[3][1] == {"id": doc.id, "type": "document"}
