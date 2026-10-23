"""QA audit unit tests for document-service (see docs/qa/document-service.md).

Tests marked ``xfail(strict=True)`` document a defect recorded in the audit report
(DOC-QA-NN); they flip to XPASS (and fail the run) once the defect is fixed.
"""

import time
import uuid

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.document import (
    DocumentCreate,
    DocumentFromTemplate,
    DocumentPatch,
    DocumentUpdate,
    TemplateCreate,
)
from app.services.document_service import DocumentService, _word_count
from tests.conftest import TEST_JWT_SECRET

DOCS = "/api/v1/documents"
TEMPLATES = "/api/v1/templates"


def _auth(user_id: uuid.UUID | str, secret: str = TEST_JWT_SECRET, **claims) -> dict:
    payload = {"user_id": str(user_id), **claims}
    return {"Authorization": f"Bearer {jwt.encode(payload, secret, algorithm='HS256')}"}


async def _create(client: AsyncClient, title: str = "Doc", content: str = "body", **extra):
    resp = await client.post(f"{DOCS}/", json={"title": title, "content": content, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _template(client: AsyncClient, **overrides) -> dict:
    body = {
        "name": "Meeting notes",
        "description": "desc",
        "content": "## Agenda\n\n- item",
        "content_type": "text/markdown",
        "created_by": str(uuid.uuid4()),
        **overrides,
    }
    resp = await client.post(f"{TEMPLATES}/", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- helpers / schemas


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("one", 1), ("  two   words ", 2), ("a\nb\tc", 3)],
)
def test_word_count(text, expected):
    assert _word_count(text) == expected


@pytest.mark.parametrize(
    ("total", "page", "size", "pages"),
    [(0, 1, 20, 1), (1, 1, 20, 1), (20, 1, 20, 1), (21, 1, 20, 2), (100, 1, 7, 15), (5, 1, 0, 1)],
)
def test_paginate(total, page, size, pages):
    assert DocumentService.paginate(total, page, size) == pages


def test_patch_schema_rejects_null_title():
    with pytest.raises(ValueError):
        DocumentPatch.model_validate({"title": None})


def test_patch_schema_tracks_only_sent_fields():
    patch = DocumentPatch.model_validate({"content": "x"})
    assert patch.model_fields_set == {"content"}


def test_create_schema_defaults():
    doc = DocumentCreate(title="t")
    assert doc.content == ""
    assert doc.content_type == "text/markdown"
    assert doc.owner_id is None


# ---------------------------------------------------------------- create validation


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": ""},
        {"title": "x" * 501},
        {"title": None},
        {"title": "ok", "owner_id": "not-a-uuid"},
        {"title": "ok", "folder_id": "nope"},
    ],
)
async def test_create_rejects_invalid_body(client: AsyncClient, body):
    resp = await client.post(f"{DOCS}/", json=body)
    assert resp.status_code == 422


async def test_create_title_at_max_length(client: AsyncClient):
    doc = await _create(client, title="x" * 500)
    assert len(doc["title"]) == 500


async def test_create_uses_jwt_owner_and_defaults(client: AsyncClient, owner_id):
    doc = await _create(client, title="Defaults", content="a b c")
    assert doc["owner_id"] == str(owner_id)
    assert doc["word_count"] == 3
    assert doc["version"] == 1
    assert doc["is_deleted"] is False
    assert doc["content_type"] == "text/markdown"


async def test_create_no_slash_route(client: AsyncClient, owner_id):
    resp = await client.post(DOCS, json={"title": "No slash"})
    assert resp.status_code == 201
    assert resp.json()["owner_id"] == str(owner_id)


async def test_create_creates_initial_version(client: AsyncClient):
    doc = await _create(client, title="V", content="first")
    versions = (await client.get(f"{DOCS}/{doc['id']}/versions")).json()
    assert [v["version_number"] for v in versions] == [1]
    assert versions[0]["content"] == "first"


@pytest.mark.xfail(strict=True, reason="DOC-QA-09: whitespace-only titles are accepted")
async def test_create_rejects_whitespace_title(client: AsyncClient):
    resp = await client.post(f"{DOCS}/", json={"title": "   "})
    assert resp.status_code == 422


# ---------------------------------------------------------------- authentication


async def test_get_requires_auth(client: AsyncClient):
    doc = await _create(client)
    resp = await client.get(f"{DOCS}/{doc['id']}", headers={"Authorization": ""})
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        "Bearer not-a-jwt",
        "Basic dXNlcjpwYXNz",
        "Bearer " + jwt.encode({"user_id": str(uuid.uuid4())}, "wrong-secret-wrong-secret-123456"),
        "Bearer " + jwt.encode({"user_id": "not-a-uuid"}, TEST_JWT_SECRET),
        "Bearer " + jwt.encode({"foo": "bar"}, TEST_JWT_SECRET),
        "Bearer "
        + jwt.encode({"user_id": str(uuid.uuid4()), "exp": int(time.time()) - 60}, TEST_JWT_SECRET),
    ],
    ids=["garbage", "basic", "wrong-secret", "bad-uuid", "no-subject", "expired"],
)
async def test_invalid_tokens_are_rejected(client: AsyncClient, header):
    doc = await _create(client)
    resp = await client.get(f"{DOCS}/{doc['id']}", headers={"Authorization": header})
    assert resp.status_code == 401


async def test_alg_none_token_rejected(client: AsyncClient):
    doc = await _create(client)
    token = jwt.encode({"user_id": str(uuid.uuid4())}, key=None, algorithm="none")
    resp = await client.get(f"{DOCS}/{doc['id']}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_sub_claim_is_accepted(client: AsyncClient):
    user = uuid.uuid4()
    token = jwt.encode({"sub": str(user)}, TEST_JWT_SECRET, algorithm="HS256")
    resp = await client.post(
        f"{DOCS}/", json={"title": "sub"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201
    assert resp.json()["owner_id"] == str(user)


async def test_x_user_id_ignored_when_secret_configured(client: AsyncClient):
    doc = await _create(client)
    resp = await client.get(
        f"{DOCS}/{doc['id']}",
        headers={"Authorization": "", "X-User-ID": doc["owner_id"]},
    )
    assert resp.status_code == 401


async def test_x_user_id_trusted_only_without_secret(client: AsyncClient, monkeypatch):
    doc = await _create(client)
    monkeypatch.setenv("JWT_SECRET", "")
    resp = await client.get(
        f"{DOCS}/{doc['id']}",
        headers={"Authorization": "Bearer opaque", "X-User-ID": doc["owner_id"]},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------- ownership


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("PUT", "", {"title": "hijack"}),
        ("PATCH", "", {"title": "hijack"}),
        ("DELETE", "", None),
        ("GET", "/versions", None),
        ("POST", "/share", None),
        ("GET", "/export", None),
    ],
)
async def test_non_owner_gets_403(client: AsyncClient, method, suffix, body):
    doc = await _create(client, title="Mine", content="secret")
    resp = await client.request(
        method, f"{DOCS}/{doc['id']}{suffix}", json=body, headers=_auth(uuid.uuid4())
    )
    assert resp.status_code == 403
    still = (await client.get(f"{DOCS}/{doc['id']}")).json()
    assert still["title"] == "Mine"


async def test_non_owner_cannot_restore_version(client: AsyncClient):
    doc = await _create(client, content="v1")
    versions = (await client.get(f"{DOCS}/{doc['id']}/versions")).json()
    resp = await client.post(
        f"{DOCS}/{doc['id']}/versions/{versions[0]['id']}/restore", headers=_auth(uuid.uuid4())
    )
    assert resp.status_code == 403


@pytest.mark.xfail(
    strict=True, reason="DOC-QA-01: owner_id query param overrides the caller's identity"
)
async def test_list_cannot_read_other_users_documents(client: AsyncClient, owner_id):
    await _create(client, title="Private")
    attacker = _auth(uuid.uuid4())
    resp = await client.get(f"{DOCS}/", params={"owner_id": str(owner_id)}, headers=attacker)
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert resp.json()["total"] == 0


@pytest.mark.xfail(strict=True, reason="DOC-QA-02: unauthenticated list returns every document")
async def test_list_requires_auth(client: AsyncClient):
    await _create(client, title="Private")
    resp = await client.get(f"{DOCS}/", headers={"Authorization": ""})
    assert resp.status_code == 401


async def test_list_is_scoped_to_caller_by_default(client: AsyncClient):
    await _create(client, title="Mine")
    resp = await client.get(f"{DOCS}/", headers=_auth(uuid.uuid4()))
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.xfail(
    strict=True, reason="DOC-QA-03: /search is unauthenticated and spans every owner"
)
async def test_search_does_not_leak_other_users_documents(client: AsyncClient):
    await _create(client, title="Quarterly secret plan")
    resp = await client.get(f"{DOCS}/search", params={"q": "secret"}, headers=_auth(uuid.uuid4()))
    assert resp.status_code in (200, 401, 403)
    if resp.status_code == 200:
        assert resp.json()["total"] == 0


@pytest.mark.xfail(strict=True, reason="DOC-QA-04: body owner_id wins over the authenticated user")
async def test_create_cannot_spoof_owner(client: AsyncClient, owner_id):
    victim = uuid.uuid4()
    resp = await client.post(f"{DOCS}/", json={"title": "planted", "owner_id": str(victim)})
    assert resp.status_code in (201, 403)
    if resp.status_code == 201:
        assert resp.json()["owner_id"] == str(owner_id)


@pytest.mark.xfail(
    strict=True, reason="DOC-QA-05: from-template has no auth; owner_id comes from the body"
)
async def test_from_template_requires_auth(client: AsyncClient):
    tpl = await _template(client)
    resp = await client.post(
        f"{DOCS}/from-template/{tpl['id']}",
        json={"title": "x", "owner_id": str(uuid.uuid4())},
        headers={"Authorization": ""},
    )
    assert resp.status_code == 401


@pytest.mark.xfail(strict=True, reason="DOC-QA-06: template endpoints have no authentication")
async def test_template_create_requires_auth(client: AsyncClient):
    resp = await client.post(
        f"{TEMPLATES}/",
        json={"name": "anon", "created_by": str(uuid.uuid4())},
        headers={"Authorization": ""},
    )
    assert resp.status_code == 401


@pytest.mark.xfail(
    strict=True, reason="DOC-QA-07: comment routes skip auth and document ownership checks"
)
async def test_comments_on_foreign_document_forbidden(client: AsyncClient):
    doc = await _create(client, title="Private")
    resp = await client.get(f"{DOCS}/{doc['id']}/comments", headers=_auth(uuid.uuid4()))
    assert resp.status_code in (401, 403)


@pytest.mark.xfail(strict=True, reason="DOC-QA-07: comment author_id is taken from the body")
async def test_comment_author_cannot_be_spoofed(client: AsyncClient, owner_id):
    doc = await _create(client)
    resp = await client.post(
        f"{DOCS}/{doc['id']}/comments",
        json={"author_id": str(uuid.uuid4()), "content": "hi"},
    )
    assert resp.status_code in (201, 403, 422)
    if resp.status_code == 201:
        assert resp.json()["author_id"] == str(owner_id)


# ---------------------------------------------------------------- update / patch / delete


async def test_put_replaces_all_fields(client: AsyncClient, folder_id):
    doc = await _create(client, title="A", content="one two", folder_id=str(folder_id))
    resp = await client.put(f"{DOCS}/{doc['id']}", json={"title": "B"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "B"
    assert data["content"] == ""
    assert data["word_count"] == 0
    assert data["folder_id"] is None
    assert data["version"] == 2


@pytest.mark.parametrize("body", [{}, {"title": ""}, {"title": "x" * 501}])
async def test_put_validation(client: AsyncClient, body):
    doc = await _create(client)
    resp = await client.put(f"{DOCS}/{doc['id']}", json=body)
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "body", [{"title": None}, {"content": None}, {"content_type": None}, {"title": ""}]
)
async def test_patch_validation(client: AsyncClient, body):
    doc = await _create(client)
    resp = await client.patch(f"{DOCS}/{doc['id']}", json=body)
    assert resp.status_code == 422


async def test_patch_empty_body_does_not_bump_version(client: AsyncClient):
    doc = await _create(client)
    resp = await client.patch(f"{DOCS}/{doc['id']}", json={})
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
    versions = (await client.get(f"{DOCS}/{doc['id']}/versions")).json()
    assert len(versions) == 1


async def test_patch_content_updates_word_count_and_versions(client: AsyncClient):
    doc = await _create(client, content="one")
    data = (await client.patch(f"{DOCS}/{doc['id']}", json={"content": "one two three"})).json()
    assert data["word_count"] == 3
    assert data["version"] == 2
    data = (await client.patch(f"{DOCS}/{doc['id']}", json={"content": ""})).json()
    assert data["word_count"] == 0
    assert data["version"] == 3


async def test_patch_can_clear_folder(client: AsyncClient, folder_id):
    doc = await _create(client, folder_id=str(folder_id))
    data = (await client.patch(f"{DOCS}/{doc['id']}", json={"folder_id": None})).json()
    assert data["folder_id"] is None


async def test_rename_persists(client: AsyncClient):
    doc = await _create(client, title="Old name", content="keep")
    await client.patch(f"{DOCS}/{doc['id']}", json={"title": "New name"})
    data = (await client.get(f"{DOCS}/{doc['id']}")).json()
    assert data["title"] == "New name"
    assert data["content"] == "keep"


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
async def test_missing_document_404(client: AsyncClient, method):
    body = {"title": "x"} if method in ("PUT", "PATCH") else None
    resp = await client.request(method, f"{DOCS}/{uuid.uuid4()}", json=body)
    assert resp.status_code == 404


async def test_invalid_document_id_422(client: AsyncClient):
    resp = await client.get(f"{DOCS}/not-a-uuid")
    assert resp.status_code == 422


async def test_delete_is_soft_and_hides_document(client: AsyncClient, db_session: AsyncSession):
    doc = await _create(client, title="Gone")
    assert (await client.delete(f"{DOCS}/{doc['id']}")).status_code == 204
    assert (await client.get(f"{DOCS}/{doc['id']}")).status_code == 404
    assert (await client.delete(f"{DOCS}/{doc['id']}")).status_code == 404
    assert (await client.patch(f"{DOCS}/{doc['id']}", json={"title": "x"})).status_code == 404
    listing = (await client.get(f"{DOCS}/")).json()
    assert all(item["id"] != doc["id"] for item in listing["items"])
    search = (await client.get(f"{DOCS}/search", params={"q": "Gone"})).json()
    assert search["total"] == 0

    from app.models.document import Document

    row = await db_session.get(Document, uuid.UUID(doc["id"]))
    await db_session.refresh(row)
    assert row is not None and row.is_deleted is True


# ---------------------------------------------------------------- versions


async def test_restore_creates_new_version(client: AsyncClient):
    doc = await _create(client, title="T1", content="first")
    await client.put(f"{DOCS}/{doc['id']}", json={"title": "T2", "content": "second"})
    versions = (await client.get(f"{DOCS}/{doc['id']}/versions")).json()
    v1 = next(v for v in versions if v["version_number"] == 1)
    restored = (await client.post(f"{DOCS}/{doc['id']}/versions/{v1['id']}/restore")).json()
    assert restored["title"] == "T1"
    assert restored["content"] == "first"
    assert restored["version"] == 3
    versions = (await client.get(f"{DOCS}/{doc['id']}/versions")).json()
    assert [v["version_number"] for v in versions] == [3, 2, 1]


async def test_restore_version_from_another_document_404(client: AsyncClient):
    a = await _create(client, title="A")
    b = await _create(client, title="B")
    b_version = (await client.get(f"{DOCS}/{b['id']}/versions")).json()[0]
    resp = await client.post(f"{DOCS}/{a['id']}/versions/{b_version['id']}/restore")
    assert resp.status_code == 404
    assert (await client.get(f"{DOCS}/{a['id']}")).json()["title"] == "A"


async def test_restore_unknown_version_404(client: AsyncClient):
    doc = await _create(client)
    resp = await client.post(f"{DOCS}/{doc['id']}/versions/{uuid.uuid4()}/restore")
    assert resp.status_code == 404


async def test_versions_of_missing_document_404(client: AsyncClient):
    resp = await client.get(f"{DOCS}/{uuid.uuid4()}/versions")
    assert resp.status_code == 404


# ---------------------------------------------------------------- list / pagination / search


@pytest.mark.parametrize("params", [{"page": 0}, {"size": 0}, {"size": 101}, {"page": "x"}])
async def test_list_pagination_validation(client: AsyncClient, params):
    resp = await client.get(f"{DOCS}/", params=params)
    assert resp.status_code == 422


async def test_list_page_past_end_is_empty(client: AsyncClient):
    for i in range(3):
        await _create(client, title=f"D{i}")
    data = (await client.get(f"{DOCS}/", params={"page": 5, "size": 2})).json()
    assert data["items"] == []
    assert data["total"] == 3
    assert data["pages"] == 2


async def test_list_pages_are_disjoint(client: AsyncClient):
    for i in range(5):
        await _create(client, title=f"D{i}")
    seen = []
    for page in (1, 2, 3):
        data = (await client.get(f"{DOCS}/", params={"page": page, "size": 2})).json()
        seen += [d["id"] for d in data["items"]]
    assert len(seen) == 5 and len(set(seen)) == 5


async def test_list_no_slash_route(client: AsyncClient):
    await _create(client)
    resp = await client.get(DOCS)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_list_filters_by_folder(client: AsyncClient, folder_id):
    await _create(client, title="in", folder_id=str(folder_id))
    await _create(client, title="out")
    data = (await client.get(f"{DOCS}/", params={"folder_id": str(folder_id)})).json()
    assert [d["title"] for d in data["items"]] == ["in"]


async def test_list_excludes_templates_flagged_documents(
    client: AsyncClient, db_session: AsyncSession, owner_id
):
    from app.models.document import Document

    db_session.add(Document(title="tpl", content="", owner_id=owner_id, is_template=True))
    await db_session.commit()
    await _create(client, title="real")
    data = (await client.get(f"{DOCS}/")).json()
    assert [d["title"] for d in data["items"]] == ["real"]


async def test_search_requires_query(client: AsyncClient):
    assert (await client.get(f"{DOCS}/search")).status_code == 422
    assert (await client.get(f"{DOCS}/search", params={"q": ""})).status_code == 422


async def test_search_matches_content_case_insensitive(client: AsyncClient):
    await _create(client, title="t", content="The Otter swims")
    data = (await client.get(f"{DOCS}/search", params={"q": "otter"})).json()
    assert data["total"] == 1


@pytest.mark.xfail(strict=True, reason="DOC-QA-08 / OW-SEC-401: title filter is SQL-injectable")
async def test_title_filter_is_not_injectable(client: AsyncClient, owner_id):
    other = uuid.uuid4()
    await client.post(f"{DOCS}/", json={"title": "victim"}, headers=_auth(other))
    payload = "%') OR 1=1 --"
    data = (await client.get(f"{DOCS}/", params={"title": payload})).json()
    assert data["total"] == 0


@pytest.mark.xfail(strict=True, reason="DOC-QA-08 / OW-SEC-401: sort is interpolated into SQL")
async def test_invalid_sort_column_rejected_cleanly(client: AsyncClient):
    await _create(client)
    resp = await client.get(f"{DOCS}/", params={"sort": "nonexistent_col"})
    assert resp.status_code == 422


async def test_invalid_sort_does_not_500(client: AsyncClient):
    await _create(client)
    resp = await client.get(f"{DOCS}/", params={"sort": "nonexistent_col"})
    assert resp.status_code < 500


# ---------------------------------------------------------------- export / share


async def test_export_rejects_unknown_format(client: AsyncClient):
    doc = await _create(client)
    resp = await client.get(f"{DOCS}/{doc['id']}/export", params={"format": "docx"})
    assert resp.status_code == 422


async def test_export_html_escapes_markup(client: AsyncClient):
    doc = await _create(client, title="<script>x</script>", content="<img src=x onerror=1>")
    resp = await client.get(f"{DOCS}/{doc['id']}/export", params={"format": "html"})
    assert resp.status_code == 200
    assert "<script>" not in resp.text
    assert "&lt;img" in resp.text


async def test_export_pdf_media_type(client: AsyncClient):
    doc = await _create(client, title="P", content="body")
    resp = await client.get(f"{DOCS}/{doc['id']}/export", params={"format": "pdf"})
    assert resp.headers["content-type"].startswith("application/pdf")
    assert "TITLE: P" in resp.text


async def test_shared_link_rejects_bad_token(client: AsyncClient):
    doc = await _create(client)
    resp = await client.get(f"{DOCS}/shared", params={"document_id": doc["id"], "token": "0" * 16})
    assert resp.status_code == 403


async def test_shared_link_for_deleted_document_404(client: AsyncClient):
    doc = await _create(client)
    token = (await client.post(f"{DOCS}/{doc['id']}/share")).json()["token"]
    await client.delete(f"{DOCS}/{doc['id']}")
    resp = await client.get(f"{DOCS}/shared", params={"document_id": doc["id"], "token": token})
    assert resp.status_code == 404


@pytest.mark.xfail(strict=True, reason="DOC-QA-10 / OW-SEC-402: export name allows path traversal")
async def test_export_archive_blocks_traversal(client: AsyncClient, monkeypatch, tmp_path):
    archive = tmp_path / "exports"
    archive.mkdir()
    (tmp_path / "outside.txt").write_text("leaked")
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(archive))
    resp = await client.get(f"{DOCS}/exports", params={"name": "../outside.txt"})
    assert resp.status_code == 404


@pytest.mark.xfail(
    strict=True, reason="DOC-QA-11 / OW-SEC-403: share tokens are unkeyed MD5 of a public salt"
)
def test_share_token_not_derivable_from_document_id():
    import hashlib

    from app.services.share_link import ShareLinkService

    doc_id = str(uuid.uuid4())
    forged = hashlib.md5(f"{doc_id}:otterworks-share".encode()).hexdigest()[:16]  # noqa: S324
    assert not ShareLinkService(salt=None).verify_token(doc_id, forged)


# ---------------------------------------------------------------- templates


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x"},
        {"name": "", "created_by": str(uuid.uuid4())},
        {"name": "x" * 501, "created_by": str(uuid.uuid4())},
        {"name": "x", "created_by": "nope"},
    ],
)
async def test_template_validation(client: AsyncClient, body):
    resp = await client.post(f"{TEMPLATES}/", json=body)
    assert resp.status_code == 422


async def test_template_defaults(client: AsyncClient):
    resp = await client.post(
        f"{TEMPLATES}/", json={"name": "Blank", "created_by": str(uuid.uuid4())}
    )
    data = resp.json()
    assert data["description"] == ""
    assert data["content"] == ""
    assert data["content_type"] == "text/markdown"


async def test_from_template_copies_content_and_versions(client: AsyncClient, owner_id, folder_id):
    tpl = await _template(client, content="one two three", content_type="text/plain")
    resp = await client.post(
        f"{DOCS}/from-template/{tpl['id']}",
        json={"title": "From tpl", "owner_id": str(owner_id), "folder_id": str(folder_id)},
    )
    assert resp.status_code == 201
    doc = resp.json()
    assert doc["content"] == "one two three"
    assert doc["content_type"] == "text/plain"
    assert doc["word_count"] == 3
    assert doc["folder_id"] == str(folder_id)
    assert doc["is_template"] is False
    fetched = await client.get(f"{DOCS}/{doc['id']}")
    assert fetched.status_code == 200
    versions = (await client.get(f"{DOCS}/{doc['id']}/versions")).json()
    assert len(versions) == 1


async def test_from_template_edit_does_not_change_template(client: AsyncClient, owner_id):
    tpl = await _template(client, content="original")
    doc = (
        await client.post(
            f"{DOCS}/from-template/{tpl['id']}", json={"title": "c", "owner_id": str(owner_id)}
        )
    ).json()
    await client.patch(f"{DOCS}/{doc['id']}", json={"content": "edited"})
    templates = (await client.get(f"{TEMPLATES}/")).json()
    assert templates[0]["content"] == "original"


@pytest.mark.parametrize("body", [{}, {"title": "x"}, {"title": "", "owner_id": str(uuid.uuid4())}])
async def test_from_template_validation(client: AsyncClient, body):
    tpl = await _template(client)
    resp = await client.post(f"{DOCS}/from-template/{tpl['id']}", json=body)
    assert resp.status_code == 422


async def test_from_template_invalid_template_id(client: AsyncClient, owner_id):
    resp = await client.post(
        f"{DOCS}/from-template/not-a-uuid", json={"title": "x", "owner_id": str(owner_id)}
    )
    assert resp.status_code == 422


async def test_templates_list_sorted(client: AsyncClient):
    for name in ("b", "c", "a"):
        await _template(client, name=name)
    names = [t["name"] for t in (await client.get(f"{TEMPLATES}/")).json()]
    assert names == ["a", "b", "c"]


# ---------------------------------------------------------------- service layer


async def test_service_update_missing_returns_none(db_session: AsyncSession):
    service = DocumentService(db_session)
    assert await service.update(uuid.uuid4(), DocumentUpdate(title="x")) is None
    assert await service.patch(uuid.uuid4(), DocumentPatch(title="x")) is None
    assert await service.restore_version(uuid.uuid4(), uuid.uuid4()) is None


async def test_service_update_records_editor(db_session: AsyncSession, owner_id):
    service = DocumentService(db_session)
    doc = await service.create(DocumentCreate(title="a", owner_id=owner_id))
    editor = uuid.uuid4()
    await service.update(doc.id, DocumentUpdate(title="b"), updated_by=editor)
    versions = await service.list_versions(doc.id)
    assert versions[0].created_by == editor
    assert versions[1].created_by == owner_id


async def test_service_publishes_events(db_session: AsyncSession, owner_id, monkeypatch):
    from app.services import document_service as mod

    events: list[str] = []

    async def _publish(event_type, payload):
        events.append(event_type)

    monkeypatch.setattr(mod.event_publisher, "publish", _publish)
    service = DocumentService(db_session)
    doc = await service.create(DocumentCreate(title="a", owner_id=owner_id))
    await service.patch(doc.id, DocumentPatch())
    await service.patch(doc.id, DocumentPatch(title="b"))
    await service.delete(doc.id)
    assert events == ["document_created", "document_updated", "document_deleted"]


async def test_service_create_from_template(db_session: AsyncSession, owner_id):
    service = DocumentService(db_session)
    tpl = await service.create_template(
        TemplateCreate(name="t", content="hello world", created_by=owner_id)
    )
    doc = await service.create_from_template(
        tpl.id, DocumentFromTemplate(title="new", owner_id=owner_id)
    )
    assert doc.content == "hello world"
    assert doc.word_count == 2
