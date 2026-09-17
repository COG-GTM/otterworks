"""Tests for request/response schema validation rules."""

import pytest
from pydantic import ValidationError

from app.schemas.document import DocumentCreate, DocumentPatch


@pytest.mark.parametrize("field", ["title", "content", "content_type"])
def test_patch_rejects_explicit_nulls_for_non_nullable_columns(field):
    with pytest.raises(ValidationError) as exc:
        DocumentPatch(**{field: None})

    assert f"{field} cannot be null" in str(exc.value)


def test_patch_allows_clearing_the_folder():
    assert DocumentPatch(folder_id=None).model_fields_set == {"folder_id"}


def test_patch_tracks_only_the_supplied_fields():
    assert DocumentPatch(title="New").model_fields_set == {"title"}


def test_create_requires_a_non_empty_title():
    with pytest.raises(ValidationError):
        DocumentCreate(title="")


def test_create_defaults_content_and_type():
    document = DocumentCreate(title="Untitled")

    assert document.content == ""
    assert document.content_type == "text/markdown"
    assert document.owner_id is None
