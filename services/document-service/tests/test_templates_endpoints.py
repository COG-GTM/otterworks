"""Unit tests for the ``app.api.templates`` endpoint handlers."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import templates
from app.schemas.document import TemplateCreate


@pytest.fixture
def service(monkeypatch) -> MagicMock:
    svc = MagicMock()
    svc.list_templates = AsyncMock()
    svc.create_template = AsyncMock()
    monkeypatch.setattr(templates, "DocumentService", lambda _db: svc)
    return svc


def _template(created_by: uuid.UUID) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Meeting Notes",
        description="",
        content="## Notes",
        content_type="text/markdown",
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_templates_returns_the_service_result(service):
    service.list_templates.return_value = [_template(uuid.uuid4())]

    result = await templates.list_templates(MagicMock())

    service.list_templates.assert_awaited_once_with()
    assert result is service.list_templates.return_value


@pytest.mark.asyncio
async def test_create_template_returns_the_created_template(service):
    created_by = uuid.uuid4()
    body = TemplateCreate(name="Meeting Notes", content="## Notes", created_by=created_by)
    service.create_template.return_value = _template(created_by)

    result = await templates.create_template(body, MagicMock())

    service.create_template.assert_awaited_once_with(body)
    assert result is service.create_template.return_value
