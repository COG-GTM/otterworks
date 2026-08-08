"""Unit tests for the ``app.api.comments`` endpoint handlers."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api import comments
from app.schemas.document import CommentCreate


@pytest.fixture
def service(monkeypatch) -> MagicMock:
    svc = MagicMock()
    svc.add_comment = AsyncMock()
    svc.list_comments = AsyncMock()
    svc.delete_comment = AsyncMock()
    monkeypatch.setattr(comments, "DocumentService", lambda _db: svc)
    return svc


def _comment(document_id: uuid.UUID, author_id: uuid.UUID) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        document_id=document_id,
        author_id=author_id,
        content="Nice doc",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_add_comment_returns_the_created_comment(service):
    document_id, author_id = uuid.uuid4(), uuid.uuid4()
    body = CommentCreate(author_id=author_id, content="Nice doc")
    service.add_comment.return_value = _comment(document_id, author_id)

    result = await comments.add_comment(document_id, body, MagicMock())

    service.add_comment.assert_awaited_once_with(document_id, body)
    assert result is service.add_comment.return_value


@pytest.mark.asyncio
async def test_add_comment_raises_404_for_an_unknown_document(service):
    service.add_comment.return_value = None

    with pytest.raises(HTTPException) as exc:
        await comments.add_comment(
            uuid.uuid4(), CommentCreate(author_id=uuid.uuid4(), content="Hi"), MagicMock()
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found"


@pytest.mark.asyncio
async def test_list_comments_returns_the_service_result(service):
    document_id = uuid.uuid4()
    service.list_comments.return_value = [_comment(document_id, uuid.uuid4())]

    result = await comments.list_comments(document_id, MagicMock())

    service.list_comments.assert_awaited_once_with(document_id)
    assert result is service.list_comments.return_value


@pytest.mark.asyncio
async def test_delete_comment_returns_no_content_on_success(service):
    document_id, comment_id = uuid.uuid4(), uuid.uuid4()
    service.delete_comment.return_value = True

    assert await comments.delete_comment(document_id, comment_id, MagicMock()) is None
    service.delete_comment.assert_awaited_once_with(document_id, comment_id)


@pytest.mark.asyncio
async def test_delete_comment_raises_404_for_an_unknown_comment(service):
    service.delete_comment.return_value = False

    with pytest.raises(HTTPException) as exc:
        await comments.delete_comment(uuid.uuid4(), uuid.uuid4(), MagicMock())

    assert exc.value.status_code == 404
    assert exc.value.detail == "Comment not found"
