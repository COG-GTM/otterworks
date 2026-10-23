"""QA audit: black-box document-service flows through the API gateway.

Findings referenced by xfail reasons are documented in docs/qa/document-service.md.
"""

import hashlib
import uuid

import pytest

pytestmark = pytest.mark.api_flow

DOCS = "/api/v1/documents"
TEMPLATES = "/api/v1/templates"


@pytest.fixture
def owner(api_client):
    return api_client.register_user("qa-doc-owner")


@pytest.fixture
def intruder(api_client):
    return api_client.register_user("qa-doc-intruder")


@pytest.fixture
def document(api_client, owner):
    return api_client.create_document(owner, f"QA Doc {api_client.run_id}", "alpha beta gamma")


def _create(api_client, user, **body):
    body.setdefault("content", "")
    response = api_client.client.post(f"{DOCS}/", headers=user.auth_headers, json=body)
    if response.status_code == 201:
        api_client.created_documents.append(response.json()["id"])
    return response


def _template(api_client, user, **overrides):
    payload = {
        "name": f"QA Template {uuid.uuid4().hex[:6]}",
        "description": "qa",
        "content": "# Heading\n\ntemplate body",
        "created_by": user.id,
    }
    payload.update(overrides)
    response = api_client.client.post(f"{TEMPLATES}/", headers=user.auth_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --- happy paths -----------------------------------------------------------------------


def test_blank_document_edit_rename_reload_delete(api_client, owner):
    headers = owner.auth_headers
    created = _create(api_client, owner, title="Untitled document")
    assert created.status_code == 201, created.text
    doc = created.json()
    assert doc["owner_id"] == owner.id
    assert doc["content"] == ""
    assert doc["word_count"] == 0
    assert doc["version"] == 1
    assert doc["content_type"] == "text/markdown"

    edited = api_client.client.patch(
        f"{DOCS}/{doc['id']}", headers=headers, json={"content": "<p>Hello QA world</p>"}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2

    renamed = api_client.client.patch(
        f"{DOCS}/{doc['id']}", headers=headers, json={"title": "Renamed by QA"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Renamed by QA"
    assert renamed.json()["content"] == "<p>Hello QA world</p>"

    reloaded = api_client.client.get(f"{DOCS}/{doc['id']}", headers=headers).json()
    assert reloaded["title"] == "Renamed by QA"
    assert reloaded["content"] == "<p>Hello QA world</p>"
    assert reloaded["version"] == 3

    listed = api_client.client.get(f"{DOCS}/", headers=headers).json()
    assert [item["id"] for item in listed["items"]] == [doc["id"]]

    deleted = api_client.client.delete(f"{DOCS}/{doc['id']}", headers=headers)
    assert deleted.status_code == 204
    assert api_client.client.get(f"{DOCS}/{doc['id']}", headers=headers).status_code == 404
    assert api_client.client.get(f"{DOCS}/", headers=headers).json()["total"] == 0
    assert api_client.client.delete(f"{DOCS}/{doc['id']}", headers=headers).status_code == 404


def test_create_from_template_copies_content(api_client, owner):
    template = _template(api_client, owner)
    listed = api_client.client.get(f"{TEMPLATES}/", headers=owner.auth_headers)
    assert listed.status_code == 200
    assert template["id"] in [t["id"] for t in listed.json()]

    response = api_client.client.post(
        f"{DOCS}/from-template/{template['id']}",
        headers=owner.auth_headers,
        json={"title": "From template", "owner_id": owner.id},
    )
    assert response.status_code == 201, response.text
    doc = response.json()
    api_client.created_documents.append(doc["id"])
    assert doc["content"] == template["content"]
    assert doc["title"] == "From template"
    assert doc["owner_id"] == owner.id
    assert doc["is_template"] is False

    fetched = api_client.client.get(f"{DOCS}/{doc['id']}", headers=owner.auth_headers)
    assert fetched.status_code == 200


def test_from_unknown_template_is_404(api_client, owner):
    response = api_client.client.post(
        f"{DOCS}/from-template/{uuid.uuid4()}",
        headers=owner.auth_headers,
        json={"title": "nope", "owner_id": owner.id},
    )
    assert response.status_code == 404


def test_put_versions_and_restore(api_client, owner, document):
    headers = owner.auth_headers
    put = api_client.client.put(
        f"{DOCS}/{document['id']}",
        headers=headers,
        json={"title": document["title"], "content": "one two"},
    )
    assert put.status_code == 200
    assert put.json()["title"] == document["title"]
    versions = api_client.client.get(f"{DOCS}/{document['id']}/versions", headers=headers).json()
    assert [v["version_number"] for v in versions] == [2, 1]
    first = next(v for v in versions if v["version_number"] == 1)
    restored = api_client.client.post(
        f"{DOCS}/{document['id']}/versions/{first['id']}/restore", headers=headers
    )
    assert restored.status_code == 200
    assert restored.json()["content"] == "alpha beta gamma"
    assert restored.json()["version"] == 3


def test_restore_unknown_version_is_404(api_client, owner, document):
    response = api_client.client.post(
        f"{DOCS}/{document['id']}/versions/{uuid.uuid4()}/restore", headers=owner.auth_headers
    )
    assert response.status_code == 404


def test_pagination_through_gateway(api_client, owner):
    for i in range(5):
        assert _create(api_client, owner, title=f"Page {i}").status_code == 201
    page = api_client.client.get(
        f"{DOCS}/", headers=owner.auth_headers, params={"page": 2, "size": 2}
    ).json()
    assert page["total"] == 5
    assert page["pages"] == 3
    assert page["page"] == 2
    assert len(page["items"]) == 2
    last = api_client.client.get(
        f"{DOCS}/", headers=owner.auth_headers, params={"page": 3, "size": 2}
    ).json()
    assert len(last["items"]) == 1
    beyond = api_client.client.get(
        f"{DOCS}/", headers=owner.auth_headers, params={"page": 9, "size": 2}
    ).json()
    assert beyond["items"] == []


@pytest.mark.parametrize("params", [{"size": 0}, {"size": 101}, {"page": 0}])
def test_pagination_bounds_rejected(api_client, owner, params):
    response = api_client.client.get(f"{DOCS}/", headers=owner.auth_headers, params=params)
    assert response.status_code == 422


def test_search_wildcards_are_literal_on_postgres(api_client, owner):
    _create(api_client, owner, title="100% done")
    _create(api_client, owner, title="1000 done")
    response = api_client.client.get(
        f"{DOCS}/search", headers=owner.auth_headers, params={"q": "100%"}
    )
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "100% done" in titles
    assert "1000 done" not in titles


def test_export_markdown_and_html(api_client, owner, document):
    md = api_client.client.get(
        f"{DOCS}/{document['id']}/export", headers=owner.auth_headers, params={"format": "markdown"}
    )
    assert md.status_code == 200
    assert document["title"] in md.text
    bad = api_client.client.get(
        f"{DOCS}/{document['id']}/export", headers=owner.auth_headers, params={"format": "docx"}
    )
    assert bad.status_code == 422


def test_share_link_round_trip(api_client, owner, intruder, document):
    minted = api_client.client.post(f"{DOCS}/{document['id']}/share", headers=owner.auth_headers)
    assert minted.status_code == 200
    token = minted.json()["token"]
    shared = api_client.client.get(
        f"{DOCS}/shared",
        headers=intruder.auth_headers,
        params={"document_id": document["id"], "token": token},
    )
    assert shared.status_code == 200
    wrong = api_client.client.get(
        f"{DOCS}/shared",
        headers=intruder.auth_headers,
        params={"document_id": document["id"], "token": "0" * 16},
    )
    assert wrong.status_code == 403
    denied = api_client.client.post(f"{DOCS}/{document['id']}/share", headers=intruder.auth_headers)
    assert denied.status_code == 403


# --- validation --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "content": "x"},
        {"title": "t" * 501, "content": "x"},
        {"content": "missing title"},
        {"title": None, "content": "x"},
    ],
)
def test_create_validation(api_client, owner, body):
    response = api_client.client.post(f"{DOCS}/", headers=owner.auth_headers, json=body)
    assert response.status_code == 422


def test_patch_null_title_rejected(api_client, owner, document):
    response = api_client.client.patch(
        f"{DOCS}/{document['id']}", headers=owner.auth_headers, json={"title": None}
    )
    assert response.status_code == 422


def test_unknown_and_malformed_ids(api_client, owner):
    headers = owner.auth_headers
    assert api_client.client.get(f"{DOCS}/{uuid.uuid4()}", headers=headers).status_code == 404
    assert api_client.client.get(f"{DOCS}/not-a-uuid", headers=headers).status_code == 422


@pytest.mark.xfail(
    strict=True, reason="DOC-QA-12: content_type longer than 50 chars returns 500 not 422"
)
def test_overlong_content_type_is_validation_error(api_client, owner):
    response = _create(api_client, owner, title="t", content_type="x" * 51)
    assert response.status_code == 422


@pytest.mark.xfail(strict=True, reason="DOC-QA-09: whitespace-only titles are accepted")
def test_whitespace_title_rejected(api_client, owner):
    assert _create(api_client, owner, title="   ").status_code == 422


# --- authn / ownership --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"{DOCS}/"),
        ("post", f"{DOCS}/"),
        ("get", f"{DOCS}/search?q=a"),
        ("get", f"{TEMPLATES}/"),
        ("get", f"{DOCS}/{uuid.uuid4()}"),
    ],
)
def test_gateway_requires_auth(api_client, method, path):
    response = getattr(api_client.client, method)(path)
    assert response.status_code == 401


def test_spoofed_x_user_id_header_is_not_trusted(api_client, owner, document):
    response = api_client.client.get(f"{DOCS}/{document['id']}", headers={"X-User-ID": owner.id})
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("put", "", {"title": "hijack"}),
        ("patch", "", {"title": "hijack"}),
        ("delete", "", None),
        ("get", "/versions", None),
        ("get", "/export", None),
    ],
)
def test_non_owner_forbidden(api_client, owner, intruder, document, method, suffix, body):
    kwargs = {"headers": intruder.auth_headers}
    if body is not None:
        kwargs["json"] = body
    response = getattr(api_client.client, method)(f"{DOCS}/{document['id']}{suffix}", **kwargs)
    assert response.status_code == 403
    still = api_client.client.get(f"{DOCS}/{document['id']}", headers=owner.auth_headers)
    assert still.status_code == 200
    assert still.json()["title"] == document["title"]


def test_list_defaults_to_caller(api_client, owner, intruder, document):
    listed = api_client.client.get(f"{DOCS}/", headers=intruder.auth_headers).json()
    assert document["id"] not in [item["id"] for item in listed["items"]]


@pytest.mark.xfail(strict=True, reason="DOC-QA-01: owner_id query param lists another user's docs")
def test_list_owner_id_param_cannot_read_others(api_client, owner, intruder, document):
    listed = api_client.client.get(
        f"{DOCS}/", headers=intruder.auth_headers, params={"owner_id": owner.id}
    ).json()
    assert document["id"] not in [item["id"] for item in listed["items"]]


@pytest.mark.xfail(strict=True, reason="DOC-QA-03: /search returns other users' documents")
def test_search_scoped_to_caller(api_client, owner, intruder):
    marker = f"qamarker{uuid.uuid4().hex[:8]}"
    _create(api_client, owner, title=marker)
    found = api_client.client.get(
        f"{DOCS}/search", headers=intruder.auth_headers, params={"q": marker}
    ).json()
    assert found["total"] == 0


@pytest.mark.xfail(strict=True, reason="DOC-QA-04: body owner_id overrides the JWT identity")
def test_create_cannot_assign_other_owner(api_client, owner, intruder):
    response = _create(api_client, intruder, title="spoofed", owner_id=owner.id)
    assert response.status_code in (201, 403)
    if response.status_code == 201:
        assert response.json()["owner_id"] == intruder.id


@pytest.mark.xfail(strict=True, reason="DOC-QA-05: from-template trusts owner_id from the body")
def test_from_template_cannot_assign_other_owner(api_client, owner, intruder):
    template = _template(api_client, intruder)
    response = api_client.client.post(
        f"{DOCS}/from-template/{template['id']}",
        headers=intruder.auth_headers,
        json={"title": "planted", "owner_id": owner.id},
    )
    if response.status_code == 201:
        api_client.created_documents.append(response.json()["id"])
        assert response.json()["owner_id"] == intruder.id
    else:
        assert response.status_code == 403


@pytest.mark.xfail(strict=True, reason="DOC-QA-07: comments skip document ownership checks")
def test_non_owner_cannot_read_comments(api_client, intruder, document):
    response = api_client.client.get(
        f"{DOCS}/{document['id']}/comments", headers=intruder.auth_headers
    )
    assert response.status_code == 403


@pytest.mark.xfail(strict=True, reason="DOC-QA-07: comment author_id is taken from the body")
def test_comment_author_cannot_be_spoofed(api_client, owner, intruder, document):
    response = api_client.client.post(
        f"{DOCS}/{document['id']}/comments",
        headers=intruder.auth_headers,
        json={"content": "spoofed", "author_id": owner.id},
    )
    assert response.status_code == 403 or response.json()["author_id"] == intruder.id


# --- injection / disclosure ----------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="DOC-QA-08 / OW-SEC-401: title filter is SQL-injectable")
def test_title_filter_injection_does_not_leak_other_owners(api_client, owner, intruder, document):
    listed = api_client.client.get(
        f"{DOCS}/", headers=intruder.auth_headers, params={"title": "%') OR 1=1 --"}
    )
    ids = [item["id"] for item in listed.json().get("items", [])]
    assert document["id"] not in ids


@pytest.mark.xfail(strict=True, reason="DOC-QA-13: invalid sort echoes raw SQL in the 400 body")
def test_invalid_sort_does_not_leak_sql(api_client, owner):
    response = api_client.client.get(
        f"{DOCS}/", headers=owner.auth_headers, params={"sort": "title; --"}
    )
    assert response.status_code == 400
    assert "SELECT" not in response.text
    assert "sqlalchemy" not in response.text


@pytest.mark.xfail(strict=True, reason="DOC-QA-10 / OW-SEC-402: /exports reads arbitrary files")
def test_export_archive_path_traversal(api_client, owner):
    response = api_client.client.get(
        f"{DOCS}/exports", headers=owner.auth_headers, params={"name": "../../../../etc/passwd"}
    )
    assert "root:" not in response.text
    assert response.status_code in (400, 404)


@pytest.mark.xfail(strict=True, reason="DOC-QA-11 / OW-SEC-403: share token is forgeable")
def test_share_token_not_forgeable(api_client, intruder, document):
    forged = hashlib.md5(f"{document['id']}:otterworks-share".encode()).hexdigest()[:16]
    response = api_client.client.get(
        f"{DOCS}/shared",
        headers=intruder.auth_headers,
        params={"document_id": document["id"], "token": forged},
    )
    assert response.status_code == 403
