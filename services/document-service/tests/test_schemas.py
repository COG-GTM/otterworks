"""Validation rules of the request schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.document import DocumentCreate, DocumentPatch


@pytest.mark.parametrize("field", ["title", "content", "content_type"])
def test_patch_rejects_an_explicit_null(field: str):
    with pytest.raises(ValidationError) as excinfo:
        DocumentPatch(**{field: None})

    assert f"{field} cannot be null" in str(excinfo.value)


def test_patch_allows_a_null_folder_id():
    assert DocumentPatch(folder_id=None).folder_id is None


def test_patch_tracks_which_fields_were_supplied():
    assert DocumentPatch(title="Only title").model_fields_set == {"title"}


def test_create_requires_a_non_empty_title():
    with pytest.raises(ValidationError):
        DocumentCreate(title="")


def test_create_defaults_content_and_content_type():
    document = DocumentCreate(title="Titled")

    assert document.content == ""
    assert document.content_type == "text/markdown"
    assert document.owner_id is None
