"""Direct unit tests of the route handlers (no ASGI stack in between)."""

import uuid

import jwt
import pytest
from fastapi import HTTPException
from httpx import Headers
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.comments import add_comment, delete_comment, list_comments
from app.api.documents import (
    create_document,
    create_document_no_slash,
    create_from_template,
    delete_document,
    export_document,
    get_document,
    list_documents,
    list_documents_no_slash,
    list_versions,
    patch_document,
    restore_version,
    search_documents,
    update_document,
)
from app.api.templates import create_template, list_templates
from app.schemas.document import (
    CommentCreate,
    DocumentCreate,
    DocumentFromTemplate,
    DocumentPatch,
    DocumentUpdate,
    TemplateCreate,
)
from app.services.document_service import DocumentService

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105


class _FakeRequest:
    def __init__(self, user_id: uuid.UUID | None = None):
        headers: dict[str, str] = {}
        if user_id is not None:
            token = jwt.encode(
                {"user_id": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256"
            )
            headers["Authorization"] = f"Bearer {token}"
        self.headers = Headers(headers)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)


async def _seed(db: AsyncSession, owner_id: uuid.UUID, title: str = "Seeded"):
    return await DocumentService(db).create(
        DocumentCreate(title=title, content="one two", owner_id=owner_id)
    )


@pytest.mark.asyncio
async def test_create_document_uses_body_owner(db_session: AsyncSession, owner_id):
    document = await create_document(
        DocumentCreate(title="Created", content="a b", owner_id=owner_id),
        _FakeRequest(),
        db_session,
    )

    assert document.title == "Created"
    assert document.owner_id == owner_id
    assert document.version == 1


@pytest.mark.asyncio
async def test_create_document_falls_back_to_token_owner(db_session: AsyncSession, owner_id):
    document = await create_document_no_slash(
        DocumentCreate(title="From token", content="a"),
        _FakeRequest(owner_id),
        db_session,
    )

    assert document.owner_id == owner_id


@pytest.mark.asyncio
async def test_create_document_without_owner_or_token_is_401(db_session: AsyncSession):
    with pytest.raises(HTTPException) as exc:
        await create_document(
            DocumentCreate(title="Anonymous", content="a"), _FakeRequest(), db_session
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_search_documents_returns_paginated_envelope(
    db_session: AsyncSession, owner_id
):
    await _seed(db_session, owner_id, title="Budget review")
    await _seed(db_session, owner_id, title="Unrelated")

    result = await search_documents(q="Budget", page=1, size=20, db=db_session)

    assert result.total == 1
    assert result.pages == 1
    assert [item.title for item in result.items] == ["Budget review"]


@pytest.mark.asyncio
async def test_list_documents_uses_token_owner_when_not_given(
    db_session: AsyncSession, owner_id
):
    await _seed(db_session, owner_id, title="Mine")

    mine = await list_documents(
        _FakeRequest(owner_id), None, None, 1, 20, db_session
    )
    other = await list_documents(
        _FakeRequest(uuid.uuid4()), None, None, 1, 20, db_session
    )

    assert [item.title for item in mine.items] == ["Mine"]
    assert other.items == []


@pytest.mark.asyncio
async def test_list_documents_no_slash_honours_explicit_owner(
    db_session: AsyncSession, owner_id
):
    await _seed(db_session, owner_id, title="Mine")

    result = await list_documents_no_slash(
        _FakeRequest(uuid.uuid4()), owner_id, None, 1, 20, db_session
    )

    assert [item.title for item in result.items] == ["Mine"]


@pytest.mark.asyncio
async def test_get_document_returns_owned_document(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    document = await get_document(seeded.id, _FakeRequest(owner_id), db_session)

    assert document.id == seeded.id


@pytest.mark.asyncio
async def test_get_document_missing_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await get_document(uuid.uuid4(), _FakeRequest(owner_id), db_session)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_document_of_other_owner_is_403(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await get_document(seeded.id, _FakeRequest(uuid.uuid4()), db_session)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_document_replaces_content(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    updated = await update_document(
        seeded.id,
        DocumentUpdate(title="Replaced", content="a b c", content_type="text/plain"),
        _FakeRequest(owner_id),
        db_session,
    )

    assert updated.title == "Replaced"
    assert updated.word_count == 3
    assert updated.version == 2


@pytest.mark.asyncio
async def test_update_document_missing_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await update_document(
            uuid.uuid4(),
            DocumentUpdate(title="T", content="c", content_type="text/plain"),
            _FakeRequest(owner_id),
            db_session,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_document_of_other_owner_is_403(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await update_document(
            seeded.id,
            DocumentUpdate(title="T", content="c", content_type="text/plain"),
            _FakeRequest(uuid.uuid4()),
            db_session,
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_patch_document_applies_single_field(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    patched = await patch_document(
        seeded.id, DocumentPatch(title="Renamed"), _FakeRequest(owner_id), db_session
    )

    assert patched.title == "Renamed"
    assert patched.content == "one two"


@pytest.mark.asyncio
async def test_patch_document_missing_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await patch_document(
            uuid.uuid4(), DocumentPatch(title="T"), _FakeRequest(owner_id), db_session
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_document_of_other_owner_is_403(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await patch_document(
            seeded.id, DocumentPatch(title="T"), _FakeRequest(uuid.uuid4()), db_session
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_document_soft_deletes(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    await delete_document(seeded.id, _FakeRequest(owner_id), db_session)

    assert await DocumentService(db_session).get(seeded.id) is None


@pytest.mark.asyncio
async def test_delete_document_missing_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await delete_document(uuid.uuid4(), _FakeRequest(owner_id), db_session)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_of_other_owner_is_403(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await delete_document(seeded.id, _FakeRequest(uuid.uuid4()), db_session)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_versions_returns_newest_first(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)
    await DocumentService(db_session).update(
        seeded.id, DocumentUpdate(title="v2", content="x", content_type="text/plain")
    )

    versions = await list_versions(seeded.id, _FakeRequest(owner_id), db_session)

    assert [v.version_number for v in versions] == [2, 1]


@pytest.mark.asyncio
async def test_list_versions_missing_document_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await list_versions(uuid.uuid4(), _FakeRequest(owner_id), db_session)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_versions_of_other_owner_is_403(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await list_versions(seeded.id, _FakeRequest(uuid.uuid4()), db_session)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_restore_version_rolls_content_back(db_session: AsyncSession, owner_id):
    service = DocumentService(db_session)
    seeded = await _seed(db_session, owner_id, title="v1")
    await service.update(
        seeded.id, DocumentUpdate(title="v2", content="new", content_type="text/plain")
    )
    first_version = (await service.list_versions(seeded.id))[-1]

    restored = await restore_version(
        seeded.id, first_version.id, _FakeRequest(owner_id), db_session
    )

    assert restored.title == "v1"
    assert restored.content == "one two"
    assert restored.version == 3


@pytest.mark.asyncio
async def test_restore_version_missing_document_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await restore_version(
            uuid.uuid4(), uuid.uuid4(), _FakeRequest(owner_id), db_session
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_restore_unknown_version_is_404(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await restore_version(
            seeded.id, uuid.uuid4(), _FakeRequest(owner_id), db_session
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_restore_version_of_other_owner_is_403(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await restore_version(
            seeded.id, uuid.uuid4(), _FakeRequest(uuid.uuid4()), db_session
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fmt", "media_type", "expected"),
    [
        ("markdown", "text/markdown", "# Exported\n\none two"),
        ("pdf", "application/pdf", "TITLE: Exported\n\none two"),
    ],
)
async def test_export_document_formats(
    db_session: AsyncSession, owner_id, fmt, media_type, expected
):
    seeded = await _seed(db_session, owner_id, title="Exported")

    response = await export_document(seeded.id, _FakeRequest(owner_id), fmt, db_session)

    assert response.media_type == media_type
    assert response.body.decode() == expected


@pytest.mark.asyncio
async def test_export_document_missing_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await export_document(
            uuid.uuid4(), _FakeRequest(owner_id), "markdown", db_session
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_export_document_of_other_owner_is_403(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await export_document(
            seeded.id, _FakeRequest(uuid.uuid4()), "markdown", db_session
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_from_template_copies_template_content(
    db_session: AsyncSession, owner_id
):
    template = await create_template(
        TemplateCreate(
            name="Brief",
            description="d",
            content="## Brief body",
            created_by=owner_id,
        ),
        db_session,
    )

    document = await create_from_template(
        template.id, DocumentFromTemplate(title="From brief", owner_id=owner_id), db_session
    )

    assert document.title == "From brief"
    assert document.content == "## Brief body"
    assert [t.name for t in await list_templates(db_session)] == ["Brief"]


@pytest.mark.asyncio
async def test_create_from_unknown_template_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await create_from_template(
            uuid.uuid4(), DocumentFromTemplate(title="T", owner_id=owner_id), db_session
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_and_list_comments(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    comment = await add_comment(
        seeded.id, CommentCreate(author_id=owner_id, content="looks good"), db_session
    )

    assert comment.content == "looks good"
    listed = await list_comments(seeded.id, db_session)
    assert [c.id for c in listed] == [comment.id]


@pytest.mark.asyncio
async def test_add_comment_to_missing_document_is_404(db_session: AsyncSession, owner_id):
    with pytest.raises(HTTPException) as exc:
        await add_comment(
            uuid.uuid4(), CommentCreate(author_id=owner_id, content="hi"), db_session
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_comment_removes_it(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)
    comment = await add_comment(
        seeded.id, CommentCreate(author_id=owner_id, content="bye"), db_session
    )

    await delete_comment(seeded.id, comment.id, db_session)

    assert await list_comments(seeded.id, db_session) == []


@pytest.mark.asyncio
async def test_delete_unknown_comment_is_404(db_session: AsyncSession, owner_id):
    seeded = await _seed(db_session, owner_id)

    with pytest.raises(HTTPException) as exc:
        await delete_comment(seeded.id, uuid.uuid4(), db_session)

    assert exc.value.status_code == 404
