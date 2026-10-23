"""QA black-box API tests for search-service through the API gateway.

Findings referenced in xfail reasons are documented in docs/qa/search-service.md
(SEARCH-QA-<n>).
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.api_flow

SEARCH = "/api/v1/search/"
INDEX_WAIT = float(os.getenv("OTTERWORKS_QA_SEARCH_INDEX_TIMEOUT", "45"))


def _token() -> str:
    return f"qa{uuid.uuid4().hex[:10]}"


def _search(api_client, user, q: str, **params: Any) -> httpx.Response:
    return api_client.client.get(SEARCH, headers=user.auth_headers, params={"q": q, **params})


def _ids(response: httpx.Response) -> list[str]:
    assert response.status_code == 200, response.text
    return [hit["id"] for hit in response.json()["results"]]


def _wait_for_hit(api_client, user, q: str, hit_id: str, **params: Any) -> dict[str, Any]:
    response = api_client.poll_until(
        lambda: _search(api_client, user, q, **params),
        lambda r: r.status_code == 200 and hit_id in _ids(r),
        timeout_seconds=INDEX_WAIT,
        description=f"{hit_id} to appear in search for {q!r}",
    )
    return next(hit for hit in response.json()["results"] if hit["id"] == hit_id)


def _index_document(api_client, user, title: str, owner_id: str | None = None, **extra: Any) -> str:
    doc_id = str(uuid.uuid4())
    response = api_client.client.post(
        "/api/v1/search/index/document",
        headers=user.auth_headers,
        json={
            "id": doc_id,
            "title": title,
            "content": extra.pop("content", f"{title} body"),
            "owner_id": owner_id or user.id,
            "created_at": extra.pop("created_at", api_client.iso_time()),
            "updated_at": api_client.iso_time(),
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    api_client.indexed_documents.append(doc_id)
    return doc_id


def _upload_file(api_client, user, name: str) -> str:
    response = api_client.client.post(
        "/api/v1/files/upload",
        headers=user.auth_headers,
        files={"file": (name, b"qa search body", "text/plain")},
    )
    assert response.status_code == 201, response.text
    file_id = response.json()["file"]["id"]
    api_client.created_files.append(file_id)
    return file_id


@pytest.fixture
def seeded(api_client) -> dict[str, Any]:
    """A user with one real document and one real file, both visible in search."""
    owner = api_client.register_user("qa-search-owner")
    token = _token()
    document = api_client.create_document(owner, f"Otter Ledger {token}", f"quarterly {token} figures")
    file_id = _upload_file(api_client, owner, f"otter-ledger-{token}.txt")
    _wait_for_hit(api_client, owner, token, document["id"])
    _wait_for_hit(api_client, owner, token, file_id)
    return {"owner": owner, "token": token, "document_id": document["id"], "file_id": file_id}


# --- authentication -------------------------------------------------------


def test_search_requires_authentication(api_client):
    response = api_client.client.get(SEARCH, params={"q": "anything"})
    assert response.status_code == 401


def test_client_supplied_user_header_is_not_trusted(api_client):
    response = api_client.client.get(
        SEARCH, params={"q": "anything"}, headers={"X-User-ID": str(uuid.uuid4())}
    )
    assert response.status_code == 401


# --- indexing pipeline + query --------------------------------------------


def test_created_document_and_file_are_searchable(api_client, seeded):
    owner, token = seeded["owner"], seeded["token"]
    body = _search(api_client, owner, token).json()
    by_id = {hit["id"]: hit for hit in body["results"]}
    doc_hit = by_id[seeded["document_id"]]
    file_hit = by_id[seeded["file_id"]]
    assert doc_hit["type"] == "document"
    assert doc_hit["title"] == f"Otter Ledger {token}"
    assert doc_hit["owner_id"] == owner.id
    assert token in doc_hit["content_snippet"]
    assert file_hit["type"] == "file"
    assert file_hit["title"] == f"otter-ledger-{token}.txt"
    assert file_hit["owner_id"] == owner.id
    assert body["query"] == token
    assert body["total"] == 2


def test_type_filter(api_client, seeded):
    owner, token = seeded["owner"], seeded["token"]
    assert _ids(_search(api_client, owner, token, type="document")) == [seeded["document_id"]]
    assert _ids(_search(api_client, owner, token, type="file")) == [seeded["file_id"]]


def test_highlights_mark_matched_terms(api_client, seeded):
    hit = next(
        h for h in _search(api_client, seeded["owner"], seeded["token"], type="document").json()["results"]
    )
    assert f"<em>{seeded['token']}</em>" in hit["highlights"]["title"][0]


def test_deleted_document_leaves_search(api_client, seeded):
    owner = seeded["owner"]
    response = api_client.client.delete(
        f"/api/v1/documents/{seeded['document_id']}", headers=owner.auth_headers
    )
    assert response.status_code in (200, 204), response.text
    api_client.poll_until(
        lambda: _search(api_client, owner, seeded["token"], type="document"),
        lambda r: seeded["document_id"] not in _ids(r),
        timeout_seconds=INDEX_WAIT,
        description="deleted document to leave the index",
    )


def test_pagination(api_client):
    user = api_client.register_user("qa-search-page")
    token = _token()
    ids = {_index_document(api_client, user, f"Paged {token} {i}") for i in range(5)}
    first = _search(api_client, user, token, type="document", page=1, size=2).json()
    second = _search(api_client, user, token, type="document", page=2, size=2).json()
    third = _search(api_client, user, token, type="document", page=3, size=2).json()
    beyond = _search(api_client, user, token, type="document", page=4, size=2).json()
    assert first["total"] == 5
    assert (len(first["results"]), len(second["results"]), len(third["results"])) == (2, 2, 1)
    assert beyond["results"] == []
    seen = [h["id"] for page in (first, second, third) for h in page["results"]]
    assert set(seen) == ids
    assert len(seen) == len(set(seen))


def test_multi_index_pagination(api_client):
    user = api_client.register_user("qa-search-mixpage")
    token = _token()
    for i in range(3):
        _index_document(api_client, user, f"Mixed {token} {i}")
    file_ids = []
    for i in range(2):
        file_id = f"qa-file-{uuid.uuid4().hex}"
        response = api_client.client.post(
            "/api/v1/search/index/file",
            headers=user.auth_headers,
            json={"id": file_id, "name": f"mixed-{token}-{i}.txt", "owner_id": user.id},
        )
        assert response.status_code == 201, response.text
        api_client.indexed_files.append(file_id)
        file_ids.append(file_id)
    pages = [_search(api_client, user, token, page=p, size=2).json() for p in (1, 2, 3)]
    assert all(p["total"] == 5 for p in pages)
    seen = [h["id"] for p in pages for h in p["results"]]
    assert len(seen) == 5
    assert len(set(seen)) == 5


# --- validation / empty / special characters -------------------------------


def test_missing_and_empty_query_are_400(api_client):
    user = api_client.register_user("qa-search-empty")
    for params in ({}, {"q": ""}):
        response = api_client.client.get(SEARCH, headers=user.auth_headers, params=params)
        assert response.status_code == 400
        assert api_client.assert_json_error(response)["error"] == "Query parameter 'q' is required"


@pytest.mark.parametrize("params", [{"page": "x"}, {"size": "abc"}])
def test_invalid_pagination_is_400(api_client, params):
    user = api_client.register_user("qa-search-badpage")
    response = api_client.client.get(SEARCH, headers=user.auth_headers, params={"q": "x", **params})
    assert response.status_code == 400
    api_client.assert_json_error(response)


def test_no_result_query_returns_empty_page(api_client):
    user = api_client.register_user("qa-search-none")
    body = _search(api_client, user, f"nothing-{_token()}").json()
    assert body["results"] == []
    assert body["total"] == 0


@pytest.mark.parametrize(
    "query",
    [
        '"unterminated',
        "<script>alert(1)</script>",
        "owner_id = \"x\" OR 1=1",
        "'; DROP TABLE documents; --",
        "%_*?\\",
        "🦦🦦",
    ],
)
def test_special_character_queries_do_not_error(api_client, query):
    user = api_client.register_user("qa-search-special")
    response = _search(api_client, user, query)
    assert response.status_code == 200, response.text
    assert response.json()["query"] == query
    assert response.json()["results"] == []


def test_unicode_title_is_searchable(api_client):
    user = api_client.register_user("qa-search-unicode")
    token = _token()
    doc_id = _index_document(api_client, user, f"Café Ōtter {token}")
    assert doc_id in _ids(_search(api_client, user, f"café {token}"))


# --- per-user isolation -----------------------------------------------------


def test_other_user_never_sees_content(api_client, seeded):
    intruder = api_client.register_user("qa-search-intruder")
    token = seeded["token"]
    assert _ids(_search(api_client, intruder, token)) == []
    assert _ids(_search(api_client, intruder, token, owner_id=seeded["owner"].id)) == []
    advanced = api_client.client.post(
        "/api/v1/search/advanced",
        headers=intruder.auth_headers,
        json={"q": token, "owner_id": seeded["owner"].id},
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["results"] == []


def test_advanced_search_scoped_and_filtered(api_client, seeded):
    owner = seeded["owner"]
    response = api_client.client.post(
        "/api/v1/search/advanced",
        headers=owner.auth_headers,
        json={"q": seeded["token"], "type": "file"},
    )
    assert response.status_code == 200, response.text
    assert [h["id"] for h in response.json()["results"]] == [seeded["file_id"]]


def test_advanced_tag_filter(api_client):
    user = api_client.register_user("qa-search-tags")
    token = _token()
    tagged = _index_document(api_client, user, f"Tagged {token}", tags=["finance"])
    _index_document(api_client, user, f"Untagged {token}", tags=["hr"])
    response = api_client.client.post(
        "/api/v1/search/advanced",
        headers=user.auth_headers,
        json={"q": token, "tags": ["finance"], "type": "document"},
    )
    assert response.status_code == 200, response.text
    assert [h["id"] for h in response.json()["results"]] == [tagged]


@pytest.mark.xfail(
    reason="SEARCH-QA-5: date_from/date_to build string range filters MeiliSearch rejects; advanced search returns 500",
    strict=True,
)
def test_advanced_date_range_filter(api_client):
    user = api_client.register_user("qa-search-dates")
    token = _token()
    old = _index_document(api_client, user, f"Archive {token}", created_at="2020-01-05T00:00:00+00:00")
    new = _index_document(api_client, user, f"Current {token}", created_at="2026-06-01T00:00:00+00:00")
    after = api_client.client.post(
        "/api/v1/search/advanced",
        headers=user.auth_headers,
        json={"q": token, "date_from": "2025-01-01"},
    )
    assert after.status_code == 200, after.text
    assert [h["id"] for h in after.json()["results"]] == [new]
    before = api_client.client.post(
        "/api/v1/search/advanced",
        headers=user.auth_headers,
        json={"q": token, "date_to": "2021-01-01"},
    )
    assert [h["id"] for h in before.json()["results"]] == [old]


@pytest.mark.xfail(
    reason="SEARCH-QA-10: a string 'tags' value is split into characters and matches nothing",
    strict=True,
)
def test_advanced_string_tag_is_single_tag(api_client):
    user = api_client.register_user("qa-search-strtag")
    token = _token()
    tagged = _index_document(api_client, user, f"Tagged {token}", tags=["finance"])
    response = api_client.client.post(
        "/api/v1/search/advanced",
        headers=user.auth_headers,
        json={"q": token, "tags": "finance"},
    )
    assert response.status_code == 400 or [h["id"] for h in response.json()["results"]] == [tagged]


@pytest.mark.xfail(
    reason="SEARCH-QA-8: unknown type values return 200/empty instead of 400 per the OpenAPI enum",
    strict=True,
)
def test_unknown_type_is_rejected(api_client):
    user = api_client.register_user("qa-search-badtype")
    assert _search(api_client, user, "x", type="spreadsheet").status_code == 400


@pytest.mark.xfail(
    reason="SEARCH-QA-9: every result's relevance score is 0.0",
    strict=True,
)
def test_results_carry_relevance_score(api_client):
    user = api_client.register_user("qa-search-score")
    token = _token()
    _index_document(api_client, user, f"Scored {token}")
    hits = _search(api_client, user, token).json()["results"]
    assert hits and all(h["score"] > 0 for h in hits)


@pytest.mark.xfail(
    reason="SEARCH-QA-11: advanced search without a JSON body returns an HTML 415 page, not a JSON error",
    strict=True,
)
def test_advanced_without_body_returns_json_error(api_client):
    user = api_client.register_user("qa-search-nobody")
    response = api_client.client.post("/api/v1/search/advanced", headers=user.auth_headers)
    api_client.assert_json_error(response)


@pytest.mark.xfail(
    reason="SEARCH-QA-12: a JSON array body to /index/document crashes with 500 instead of 400",
    strict=True,
)
def test_index_array_body_is_400(api_client):
    user = api_client.register_user("qa-search-array")
    response = api_client.client.post(
        "/api/v1/search/index/document", headers=user.auth_headers, json=[{"id": "x"}]
    )
    assert response.status_code == 400


@pytest.mark.xfail(
    reason="SEARCH-QA-1: /suggest is not scoped to the caller and leaks other users' document titles",
    strict=True,
)
def test_suggest_does_not_leak_other_users_titles(api_client, seeded):
    intruder = api_client.register_user("qa-search-suggest")
    response = api_client.client.get(
        "/api/v1/search/suggest", headers=intruder.auth_headers, params={"q": seeded["token"]}
    )
    assert response.status_code == 200, response.text
    assert not any(seeded["token"] in s for s in response.json()["suggestions"])


@pytest.mark.xfail(
    reason="SEARCH-QA-7: /analytics is global and exposes every user's raw search queries",
    strict=True,
)
def test_analytics_does_not_leak_other_users_queries(api_client):
    victim = api_client.register_user("qa-search-an-victim")
    intruder = api_client.register_user("qa-search-an-intruder")
    secret = f"acquisition-{_token()}"
    _search(api_client, victim, secret)
    response = api_client.client.get("/api/v1/search/analytics", headers=intruder.auth_headers)
    assert response.status_code in (200, 403)
    assert secret not in response.text


@pytest.mark.xfail(
    reason="SEARCH-QA-2: index endpoints are routed to end users and trust owner_id from the body (result poisoning)",
    strict=True,
)
def test_user_cannot_plant_results_for_another_user(api_client):
    victim = api_client.register_user("qa-search-plant-victim")
    attacker = api_client.register_user("qa-search-plant-attacker")
    token = _token()
    doc_id = str(uuid.uuid4())
    response = api_client.client.post(
        "/api/v1/search/index/document",
        headers=attacker.auth_headers,
        json={"id": doc_id, "title": f"Reset your password {token}", "owner_id": victim.id},
    )
    if response.status_code == 201:
        api_client.indexed_documents.append(doc_id)
    assert doc_id not in _ids(_search(api_client, victim, token))


@pytest.mark.xfail(
    reason="SEARCH-QA-3: DELETE /search/index/<type>/<id> lets any user remove another user's index entry",
    strict=True,
)
def test_user_cannot_delete_other_users_index_entry(api_client, seeded):
    intruder = api_client.register_user("qa-search-deleter")
    api_client.client.delete(
        f"/api/v1/search/index/document/{seeded['document_id']}", headers=intruder.auth_headers
    )
    assert seeded["document_id"] in _ids(_search(api_client, seeded["owner"], seeded["token"]))


@pytest.mark.skipif(
    os.getenv("OTTERWORKS_QA_DESTRUCTIVE") != "1",
    reason="drops every search index on the target stack; set OTTERWORKS_QA_DESTRUCTIVE=1 to run",
)
@pytest.mark.xfail(
    reason="SEARCH-QA-4: any authenticated end user can POST /search/reindex (drops and rebuilds every index)",
    strict=True,
)
def test_reindex_is_not_a_user_operation(api_client):
    intruder = api_client.register_user("qa-search-reindex")
    response = api_client.client.post("/api/v1/search/reindex", headers=intruder.auth_headers)
    assert response.status_code in (401, 403), response.text
