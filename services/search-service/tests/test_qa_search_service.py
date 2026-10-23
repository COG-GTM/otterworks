"""QA audit unit tests for the search-service.

Findings referenced in xfail reasons are documented in docs/qa/search-service.md
(SEARCH-QA-<n>).
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import meilisearch
import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app
from app.services.indexer import Indexer
from app.services.meilisearch_client import MeiliSearchService, get_search_analytics
from app.services.sqs_consumer import SQSConsumer

DOCS_INDEX = "test-otterworks-documents"
FILES_INDEX = "test-otterworks-files"
SERVICE_TOKEN = "qa-service-token"


def _task(uid: int = 1) -> MagicMock:
    task = MagicMock()
    task.task_uid = uid
    return task


def _make_index(hits: list[dict] | None = None, total: int | None = None) -> MagicMock:
    index = MagicMock()
    index.add_documents.return_value = _task()
    index.delete_document.return_value = _task()
    hits = hits or []
    index.search.return_value = {
        "hits": hits,
        "estimatedTotalHits": len(hits) if total is None else total,
    }
    return index


def _meili_api_error(message: str = "invalid filter") -> meilisearch.errors.MeilisearchApiError:
    response = MagicMock()
    response.status_code = 400
    response.text = json.dumps({"message": message, "code": "invalid_search_filter"})
    return meilisearch.errors.MeilisearchApiError(message, response)


@pytest.fixture()
def docs_index() -> MagicMock:
    return _make_index()


@pytest.fixture()
def files_index() -> MagicMock:
    return _make_index()


@pytest.fixture()
def meili(docs_index: MagicMock, files_index: MagicMock) -> MagicMock:
    client = MagicMock()
    result = MagicMock()
    result.status = "succeeded"
    client.wait_for_task.return_value = result
    client.create_index.return_value = _task()
    client.delete_index.return_value = _task()
    client.index.side_effect = lambda name: docs_index if name == DOCS_INDEX else files_index
    return client


def _config(require_auth: bool, service_token: str = "") -> AppConfig:
    return AppConfig(
        service_name="search-service-qa",
        log_level="WARNING",
        meilisearch=MeiliSearchConfig(
            url="http://localhost:7700",
            api_key="",
            documents_index=DOCS_INDEX,
            files_index=FILES_INDEX,
        ),
        sqs=SQSConfig(enabled=False),
        auth=AuthConfig(service_token=service_token, require_auth=require_auth),
    )


def _build_client(meili: MagicMock, require_auth: bool, service_token: str = ""):
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = meili
        app = create_app(_config(require_auth, service_token))
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def client(meili: MagicMock):
    """App with auth enforced exactly like production (no service token)."""
    return _build_client(meili, require_auth=True)


@pytest.fixture()
def token_client(meili: MagicMock):
    return _build_client(meili, require_auth=True, service_token=SERVICE_TOKEN)


def _user() -> dict[str, str]:
    return {"X-User-ID": f"user-{uuid.uuid4().hex[:8]}"}


def _filter_of(index: MagicMock) -> str:
    params = index.search.call_args[0][1]
    return params.get("filter", "")


# ---------------------------------------------------------------------------
# Authentication middleware
# ---------------------------------------------------------------------------


class TestAuthMiddleware:
    def test_health_is_public(self, client):
        assert client.get("/health").status_code == 200

    def test_metrics_is_public(self, client):
        assert client.get("/metrics").status_code == 200

    def test_ready_is_public(self, client, meili):
        meili.health.return_value = {"status": "available"}
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.get_json() == {"ready": True}

    def test_search_without_identity_is_401_json(self, client):
        response = client.get("/api/v1/search/?q=x")
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}

    def test_blank_user_header_is_rejected(self, client):
        response = client.get("/api/v1/search/?q=x", headers={"X-User-ID": "   "})
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/v1/search/suggest?q=ab"),
            ("post", "/api/v1/search/advanced"),
            ("get", "/api/v1/search/analytics"),
            ("post", "/api/v1/search/index/document"),
            ("post", "/api/v1/search/index/file"),
            ("delete", "/api/v1/search/index/document/abc"),
            ("post", "/api/v1/search/reindex"),
        ],
    )
    def test_every_api_route_requires_identity(self, client, method, path):
        response = getattr(client, method)(path)
        assert response.status_code == 401

    def test_gateway_identity_is_accepted(self, client):
        assert client.get("/api/v1/search/?q=x", headers=_user()).status_code == 200

    def test_arbitrary_bearer_without_service_token_is_rejected(self, client):
        response = client.get(
            "/api/v1/search/?q=x", headers={"Authorization": "Bearer anything"}
        )
        assert response.status_code == 401

    def test_valid_service_token_is_accepted(self, token_client):
        response = token_client.get(
            "/api/v1/search/?q=x", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}
        )
        assert response.status_code == 200

    def test_wrong_service_token_is_rejected(self, token_client):
        response = token_client.get(
            "/api/v1/search/?q=x", headers={"Authorization": "Bearer nope"}
        )
        assert response.status_code == 401

    def test_auth_can_be_disabled(self, meili):
        open_client = _build_client(meili, require_auth=False)
        assert open_client.get("/api/v1/search/?q=x").status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/search/
# ---------------------------------------------------------------------------


class TestSearchQuery:
    def test_missing_query_is_400(self, client):
        response = client.get("/api/v1/search/", headers=_user())
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_empty_query_is_400(self, client):
        assert client.get("/api/v1/search/?q=", headers=_user()).status_code == 400

    def test_results_scoped_to_gateway_user(self, client, docs_index, files_index):
        headers = {"X-User-ID": "owner-a"}
        client.get("/api/v1/search/?q=report", headers=headers)
        assert _filter_of(docs_index) == 'owner_id = "owner-a"'
        assert _filter_of(files_index) == 'owner_id = "owner-a"'

    def test_owner_id_query_param_cannot_override_identity(self, client, docs_index):
        client.get("/api/v1/search/?q=report&owner_id=victim", headers={"X-User-ID": "attacker"})
        flt = _filter_of(docs_index)
        assert 'owner_id = "attacker"' in flt
        assert "victim" not in flt

    def test_owner_id_is_filter_escaped(self, client, docs_index):
        client.get("/api/v1/search/?q=x", headers={"X-User-ID": 'a" OR owner_id = "b'})
        assert _filter_of(docs_index) == 'owner_id = "a\\" OR owner_id = \\"b"'

    def test_type_document_only_searches_documents_index(self, client, meili, docs_index, files_index):
        client.get("/api/v1/search/?q=x&type=document", headers={"X-User-ID": "u"})
        docs_index.search.assert_called_once()
        files_index.search.assert_not_called()
        assert _filter_of(docs_index) == 'type = "document" AND owner_id = "u"'

    def test_type_file_only_searches_files_index(self, client, docs_index, files_index):
        client.get("/api/v1/search/?q=x&type=file", headers={"X-User-ID": "u"})
        files_index.search.assert_called_once()
        docs_index.search.assert_not_called()

    def test_type_filter_value_is_escaped(self, client, docs_index):
        client.get('/api/v1/search/?q=x&type=a"b', headers={"X-User-ID": "u"})
        assert 'type = "a\\"b"' in _filter_of(docs_index)

    @pytest.mark.xfail(
        reason="SEARCH-QA-8: unknown type values are accepted (200, empty) instead of 400 per the OpenAPI enum",
        strict=True,
    )
    def test_unknown_type_rejected(self, client):
        response = client.get("/api/v1/search/?q=x&type=spreadsheet", headers=_user())
        assert response.status_code == 400

    @pytest.mark.parametrize(
        "query",
        [
            '"quoted phrase"',
            "<script>alert(1)</script>",
            "'; DROP TABLE documents; --",
            "owner_id = \"x\" OR 1=1",
            "naïve café 日本語 🦦",
            "%_*?\\",
        ],
    )
    def test_special_character_queries_pass_through_verbatim(self, client, docs_index, query):
        response = client.get("/api/v1/search/", query_string={"q": query}, headers={"X-User-ID": "u"})
        assert response.status_code == 200
        assert response.get_json()["query"] == query
        assert docs_index.search.call_args[0][0] == query
        assert _filter_of(docs_index) == 'owner_id = "u"'

    def test_single_index_pagination_uses_offset(self, client, docs_index):
        client.get("/api/v1/search/?q=x&type=document&page=3&size=5", headers=_user())
        params = docs_index.search.call_args[0][1]
        assert params["offset"] == 10
        assert params["limit"] == 5

    def test_multi_index_pagination_merges_and_slices(self, client, docs_index, files_index):
        docs_index.search.return_value = {
            "hits": [{"id": f"d{i}", "title": f"D{i}"} for i in range(4)],
            "estimatedTotalHits": 4,
        }
        files_index.search.return_value = {
            "hits": [{"id": f"f{i}", "name": f"F{i}"} for i in range(4)],
            "estimatedTotalHits": 4,
        }
        response = client.get("/api/v1/search/?q=x&page=2&size=3", headers=_user())
        body = response.get_json()
        assert docs_index.search.call_args[0][1]["limit"] == 6
        assert docs_index.search.call_args[0][1]["offset"] == 0
        assert body["total"] == 8
        assert [r["id"] for r in body["results"]] == ["d3", "f0", "f1"]
        assert body["page"] == 2
        assert body["page_size"] == 3

    @pytest.mark.parametrize(
        "params,expected_page,expected_size",
        [("page=0&size=0", 1, 1), ("page=-4&size=1000", 1, 100), ("size=100", 1, 100)],
    )
    def test_page_and_size_are_clamped(self, client, params, expected_page, expected_size):
        body = client.get(f"/api/v1/search/?q=x&{params}", headers=_user()).get_json()
        assert body["page"] == expected_page
        assert body["page_size"] == expected_size

    @pytest.mark.parametrize("params", ["page=abc", "size=1.5", "page=", "size=ten"])
    def test_invalid_page_or_size_is_400(self, client, params):
        response = client.get(f"/api/v1/search/?q=x&{params}", headers=_user())
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid page or size parameter"}

    def test_meilisearch_filter_error_maps_to_400(self, client, docs_index):
        docs_index.search.side_effect = _meili_api_error("bad filter")
        response = client.get("/api/v1/search/?q=x", headers=_user())
        assert response.status_code == 400
        assert "Invalid search filter" in response.get_json()["error"]

    def test_unexpected_backend_error_is_500_without_leak(self, client, docs_index):
        docs_index.search.side_effect = ConnectionError("meili down at 10.0.0.1")
        response = client.get("/api/v1/search/?q=x", headers=_user())
        assert response.status_code == 500
        assert response.get_json() == {"error": "Search failed"}
        assert b"10.0.0.1" not in response.data

    def test_hit_mapping_for_documents_and_files(self, client, docs_index, files_index):
        docs_index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [
                {
                    "id": "d1",
                    "title": "Budget",
                    "content": "x" * 500,
                    "owner_id": "u",
                    "tags": ["fin"],
                    "_formatted": {"title": "<em>Budget</em>", "content": "y" * 500},
                }
            ],
        }
        files_index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [
                {
                    "id": "f1",
                    "name": "budget.xlsx",
                    "mime_type": "application/vnd.ms-excel",
                    "size": 42,
                    "folder_id": "fold",
                    "owner_id": "u",
                    "_formatted": {"name": "budget.xlsx"},
                }
            ],
        }
        results = client.get("/api/v1/search/?q=budget", headers={"X-User-ID": "u"}).get_json()["results"]
        doc, file_hit = results
        assert doc["type"] == "document"
        assert doc["title"] == "Budget"
        assert len(doc["content_snippet"]) == 200
        assert doc["highlights"] == {"title": ["<em>Budget</em>"]}
        assert file_hit["type"] == "file"
        assert file_hit["title"] == "budget.xlsx"
        assert file_hit["content_snippet"] == ""
        assert file_hit["highlights"] == {}
        assert file_hit["mime_type"] == "application/vnd.ms-excel"
        assert file_hit["size"] == 42

    @pytest.mark.xfail(
        reason="SEARCH-QA-9: relevance score is hard-coded to 0.0; ranking score is never requested from MeiliSearch",
        strict=True,
    )
    def test_relevance_score_is_populated(self, client, docs_index):
        docs_index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [{"id": "d1", "title": "t", "_rankingScore": 0.87}],
        }
        client.get("/api/v1/search/?q=t&type=document", headers=_user())
        params = docs_index.search.call_args[0][1]
        assert params.get("showRankingScore") is True


# ---------------------------------------------------------------------------
# GET /api/v1/search/suggest
# ---------------------------------------------------------------------------


class TestSuggest:
    @pytest.mark.parametrize("q", ["", "a"])
    def test_short_prefix_returns_empty_without_backend_call(self, client, docs_index, q):
        response = client.get("/api/v1/search/suggest", query_string={"q": q}, headers=_user())
        assert response.status_code == 200
        assert response.get_json() == {"suggestions": [], "query": q}
        docs_index.search.assert_not_called()

    def test_suggestions_deduplicated_across_indices(self, client, docs_index, files_index):
        docs_index.search.return_value = {"hits": [{"title": "Plan"}, {"title": "Plan"}, {"title": "Pla"}]}
        files_index.search.return_value = {"hits": [{"name": "Plan"}, {"name": "plan.pdf"}]}
        body = client.get("/api/v1/search/suggest?q=pl", headers=_user()).get_json()
        assert body["suggestions"] == ["Plan", "Pla", "plan.pdf"]

    def test_backend_failure_degrades_to_empty(self, client, docs_index):
        docs_index.search.side_effect = RuntimeError("down")
        response = client.get("/api/v1/search/suggest?q=pl", headers=_user())
        assert response.status_code == 200
        assert response.get_json()["suggestions"] == []

    @pytest.mark.xfail(
        reason="SEARCH-QA-1: suggest ignores X-User-ID and returns titles from every user's documents/files",
        strict=True,
    )
    def test_suggestions_scoped_to_user(self, client, docs_index):
        client.get("/api/v1/search/suggest?q=pl", headers={"X-User-ID": "owner-a"})
        params = docs_index.search.call_args[0][1]
        assert 'owner_id = "owner-a"' in params.get("filter", "")


# ---------------------------------------------------------------------------
# POST /api/v1/search/advanced
# ---------------------------------------------------------------------------


class TestAdvancedSearch:
    def test_owner_from_header_not_body(self, client, docs_index):
        client.post(
            "/api/v1/search/advanced",
            json={"q": "x", "owner_id": "victim"},
            headers={"X-User-ID": "attacker"},
        )
        flt = _filter_of(docs_index)
        assert 'owner_id = "attacker"' in flt
        assert "victim" not in flt

    def test_full_filter_expression(self, client, docs_index):
        client.post(
            "/api/v1/search/advanced",
            json={
                "q": "budget",
                "type": "document",
                "tags": ["fin", 'q"4'],
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
            },
            headers={"X-User-ID": "u"},
        )
        assert _filter_of(docs_index) == (
            'type = "document" AND owner_id = "u" AND (tags = "fin" OR tags = "q\\"4") '
            'AND created_at >= "2024-01-01" AND created_at <= "2024-12-31"'
        )

    def test_empty_body_returns_placeholder_search(self, client, docs_index):
        response = client.post("/api/v1/search/advanced", json={}, headers={"X-User-ID": "u"})
        assert response.status_code == 200
        assert response.get_json()["query"] == "*"
        assert docs_index.search.call_args[0][0] == ""
        assert _filter_of(docs_index) == 'owner_id = "u"'

    @pytest.mark.parametrize("body", [{"page": "x"}, {"size": "y"}, {"page": None}])
    def test_invalid_pagination_is_400(self, client, body):
        response = client.post("/api/v1/search/advanced", json=body, headers=_user())
        assert response.status_code == 400

    def test_size_is_clamped(self, client):
        body = client.post("/api/v1/search/advanced", json={"size": 5000, "page": -1}, headers=_user()).get_json()
        assert body["page_size"] == 100
        assert body["page"] == 1

    @pytest.mark.xfail(
        reason="SEARCH-QA-5: MeiliSearch filter errors in advanced search surface as 500 instead of 400",
        strict=True,
    )
    def test_filter_error_maps_to_400(self, client, docs_index):
        docs_index.search.side_effect = _meili_api_error("created_at is not filterable as string")
        response = client.post("/api/v1/search/advanced", json={"date_from": "yesterday"}, headers=_user())
        assert response.status_code == 400

    @pytest.mark.xfail(
        reason="SEARCH-QA-10: a string 'tags' value is iterated character by character into the filter",
        strict=True,
    )
    def test_string_tags_treated_as_single_tag_or_rejected(self, client, docs_index):
        response = client.post("/api/v1/search/advanced", json={"tags": "finance"}, headers=_user())
        if response.status_code == 400:
            return
        assert 'tags = "finance"' in _filter_of(docs_index)

    @pytest.mark.xfail(
        reason="SEARCH-QA-11: body-less POST returns an HTML 415 page instead of a JSON response",
        strict=True,
    )
    def test_body_less_post_returns_json(self, client):
        response = client.post("/api/v1/search/advanced", headers=_user())
        assert response.is_json


# ---------------------------------------------------------------------------
# Indexing endpoints
# ---------------------------------------------------------------------------


class TestIndexing:
    def test_index_document_forces_type(self, client, docs_index):
        response = client.post(
            "/api/v1/search/index/document",
            json={"id": "d1", "title": "T", "type": "file", "owner_id": "u"},
            headers={"X-User-ID": "u"},
        )
        assert response.status_code == 201
        assert response.get_json() == {"status": "indexed", "id": "d1", "type": "document"}
        stored = docs_index.add_documents.call_args[0][0][0]
        assert stored["type"] == "document"
        assert stored["content"] == ""
        assert stored["tags"] == []

    def test_index_file_defaults(self, client, files_index):
        response = client.post(
            "/api/v1/search/index/file", json={"id": "f1", "name": "a.txt"}, headers=_user()
        )
        assert response.status_code == 201
        stored = files_index.add_documents.call_args[0][0][0]
        assert stored == {
            "id": "f1",
            "name": "a.txt",
            "mime_type": "",
            "owner_id": "",
            "folder_id": "",
            "tags": [],
            "size": 0,
            "created_at": None,
            "updated_at": None,
            "type": "file",
        }

    @pytest.mark.parametrize(
        "path,body,message",
        [
            ("document", {"title": "t"}, "Document 'id' is required"),
            ("document", {"id": "d"}, "Document 'title' is required"),
            ("document", {"id": "d", "title": ""}, "Document 'title' is required"),
            ("file", {"name": "n"}, "File 'id' is required"),
            ("file", {"id": "f"}, "File 'name' is required"),
        ],
    )
    def test_required_field_validation(self, client, path, body, message):
        response = client.post(f"/api/v1/search/index/{path}", json=body, headers=_user())
        assert response.status_code == 400
        assert response.get_json() == {"error": message}

    def test_meilisearch_task_failure_is_500(self, client, meili):
        failed = MagicMock()
        failed.status = "failed"
        failed.error = {"code": "internal"}
        meili.wait_for_task.return_value = failed
        response = client.post(
            "/api/v1/search/index/document", json={"id": "d", "title": "t"}, headers=_user()
        )
        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index document"}

    def test_file_lmdb_key_exists_is_retried(self, client, meili, files_index):
        failed = MagicMock()
        failed.status = "failed"
        failed.error = "MDB_KEYEXIST"
        ok = MagicMock()
        ok.status = "succeeded"
        meili.wait_for_task.side_effect = [failed, ok, ok]
        response = client.post(
            "/api/v1/search/index/file", json={"id": "f", "name": "n"}, headers=_user()
        )
        assert response.status_code == 201
        files_index.delete_document.assert_called_once_with("f")
        assert files_index.add_documents.call_count == 2

    @pytest.mark.xfail(
        reason="SEARCH-QA-12: a JSON array body raises AttributeError and returns 500 instead of 400",
        strict=True,
    )
    def test_non_object_body_is_400(self, client):
        response = client.post("/api/v1/search/index/document", json=[{"id": "d"}], headers=_user())
        assert response.status_code == 400

    @pytest.mark.xfail(
        reason="SEARCH-QA-11: empty JSON body returns Flask's HTML 400 page, not the documented JSON ErrorResponse",
        strict=True,
    )
    def test_empty_json_body_returns_json_error(self, client):
        response = client.post(
            "/api/v1/search/index/document", data="", content_type="application/json", headers=_user()
        )
        assert response.status_code == 400
        assert response.is_json

    @pytest.mark.xfail(
        reason="SEARCH-QA-2: index endpoints trust owner_id from the body; a gateway user can plant entries in another user's results",
        strict=True,
    )
    def test_gateway_user_cannot_index_for_another_owner(self, client, docs_index):
        response = client.post(
            "/api/v1/search/index/document",
            json={"id": "d1", "title": "Phish", "owner_id": "victim"},
            headers={"X-User-ID": "attacker"},
        )
        if response.status_code in (401, 403):
            return
        assert docs_index.add_documents.call_args[0][0][0]["owner_id"] == "attacker"

    def test_delete_existing_returns_200(self, client, docs_index):
        docs_index.get_document.return_value = {"id": "d1"}
        response = client.delete("/api/v1/search/index/document/d1", headers=_user())
        assert response.status_code == 200
        assert response.get_json() == {"status": "deleted", "id": "d1", "type": "document"}
        docs_index.delete_document.assert_called_once_with("d1")

    def test_delete_missing_returns_404(self, client, files_index):
        files_index.get_document.side_effect = _meili_api_error("not found")
        response = client.delete("/api/v1/search/index/file/nope", headers=_user())
        assert response.status_code == 404
        assert response.get_json()["status"] == "not_found"

    def test_delete_invalid_type_returns_400(self, client):
        response = client.delete("/api/v1/search/index/folder/x", headers=_user())
        assert response.status_code == 400

    @pytest.mark.xfail(
        reason="SEARCH-QA-3: DELETE /index/<type>/<id> has no ownership check; any user can remove another user's entries",
        strict=True,
    )
    def test_delete_of_other_users_entry_is_refused(self, client, docs_index):
        docs_index.get_document.return_value = {"id": "d1", "owner_id": "victim"}
        response = client.delete("/api/v1/search/index/document/d1", headers={"X-User-ID": "attacker"})
        assert response.status_code in (403, 404)
        docs_index.delete_document.assert_not_called()

    @pytest.mark.xfail(
        reason="SEARCH-QA-4: POST /reindex (drops both indices) is open to any authenticated gateway user",
        strict=True,
    )
    def test_reindex_requires_service_token(self, token_client, meili):
        with patch("app.services.indexer.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"documents": []}
            response = token_client.post("/api/v1/search/reindex", headers=_user())
        assert response.status_code in (401, 403)
        meili.delete_index.assert_not_called()

    def test_reindex_with_service_token_repopulates(self, token_client, meili, docs_index, files_index):
        pages = {
            ("document", 1): {"documents": [{"id": "d1", "title": "T", "owner_id": "u"}]},
            ("file", 1): {"files": [{"id": "f1", "name": "n", "ownerId": "u", "sizeBytes": 3}]},
        }

        def fake_get(url, params, timeout):
            kind = "document" if "documents" in url else "file"
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = pages.get((kind, params["page"]), {})
            return resp

        with patch("app.services.indexer.requests.get", side_effect=fake_get):
            response = token_client.post(
                "/api/v1/search/reindex", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}
            )
        assert response.status_code == 200
        assert response.get_json()["indexed_counts"] == {"documents": 1, "files": 1}
        assert files_index.add_documents.call_args[0][0][0]["size"] == 3
        assert files_index.add_documents.call_args[0][0][0]["owner_id"] == "u"

    @pytest.mark.xfail(
        reason="SEARCH-QA-6: reindex crawls document/file services without any identity, gets 401, and wipes both indices",
        strict=True,
    )
    def test_reindex_does_not_wipe_when_sources_reject(self, token_client, meili):
        with patch("app.services.indexer.requests.get") as get:
            get.return_value.status_code = 401
            token_client.post(
                "/api/v1/search/reindex", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}
            )
        meili.delete_index.assert_not_called()


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class TestAnalytics:
    def test_analytics_counts_queries_and_zero_results(self, client):
        marker = f"qa-zero-{uuid.uuid4().hex[:6]}"
        before = get_search_analytics().total_searches
        client.get(f"/api/v1/search/?q={marker}", headers=_user())
        body = client.get("/api/v1/search/analytics", headers=_user()).get_json()
        assert body["total_searches"] == before + 1
        assert {"query": marker, "count": 1} in body["zero_result_queries"]

    @pytest.mark.xfail(
        reason="SEARCH-QA-7: analytics is global; any user can read every other user's search queries",
        strict=True,
    )
    def test_analytics_scoped_to_user(self, client):
        marker = f"secret-merger-{uuid.uuid4().hex[:6]}"
        client.get(f"/api/v1/search/?q={marker}", headers={"X-User-ID": "owner-a"})
        body = client.get("/api/v1/search/analytics", headers={"X-User-ID": "owner-b"}).get_json()
        assert marker not in json.dumps(body)


# ---------------------------------------------------------------------------
# MeiliSearchService helpers
# ---------------------------------------------------------------------------


class TestMeiliSearchServiceHelpers:
    @pytest.fixture()
    def service(self, meili) -> MeiliSearchService:
        with patch("app.services.meilisearch_client.meilisearch.Client", return_value=meili):
            return MeiliSearchService(_config(False).meilisearch)

    @pytest.mark.parametrize(
        "raw,escaped",
        [("plain", "plain"), ('a"b', 'a\\"b'), ("a\\b", "a\\\\b"), ('\\"', '\\\\\\"')],
    )
    def test_escape(self, raw, escaped):
        assert MeiliSearchService._escape(raw) == escaped

    def test_ensure_indices_creates_missing(self, service, meili):
        meili.get_index.side_effect = _meili_api_error("missing")
        service.ensure_indices()
        assert meili.create_index.call_count == 2
        meili.create_index.assert_any_call(DOCS_INDEX, {"primaryKey": "id"})

    def test_ensure_indices_configures_owner_filterable(self, service, docs_index, files_index):
        service.ensure_indices()
        assert "owner_id" in docs_index.update_filterable_attributes.call_args[0][0]
        assert "owner_id" in files_index.update_filterable_attributes.call_args[0][0]

    def test_ping(self, service, meili):
        assert service.ping() is True
        meili.health.side_effect = RuntimeError
        assert service.ping() is False


# ---------------------------------------------------------------------------
# SQS event normalisation (document-service / file-service -> indexer)
# ---------------------------------------------------------------------------


class TestSqsNormalisation:
    def test_document_created_event(self):
        event = SQSConsumer._normalize_event(
            {"event_type": "document_created", "payload": {"id": "d", "title": "T", "owner_id": "u"}}
        )
        assert event == {"action": "index_document", "data": {"id": "d", "title": "T", "owner_id": "u"}}

    def test_document_deleted_event(self):
        event = SQSConsumer._normalize_event(
            {"event_type": "document_deleted", "payload": {"id": "d", "type": "document"}}
        )
        assert event["action"] == "delete"

    def test_file_uploaded_camel_case_event(self):
        event = SQSConsumer._normalize_event(
            {
                "eventType": "file_uploaded",
                "fileId": "f",
                "ownerId": "u",
                "folderId": None,
                "name": "a.pdf",
                "mimeType": "application/pdf",
                "sizeBytes": 9,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        assert event["action"] == "index_file"
        assert event["data"]["owner_id"] == "u"
        assert event["data"]["name"] == "a.pdf"
        assert event["data"]["size"] == 9

    @pytest.mark.parametrize("event_type", ["file_trashed", "file_deleted"])
    def test_file_removal_events(self, event_type):
        event = SQSConsumer._normalize_event({"eventType": event_type, "fileId": "f"})
        assert event == {"action": "delete", "data": {"type": "file", "id": "f"}}

    def test_file_shared_event_is_ignored_by_indexer(self):
        body = {"eventType": "file_shared", "fileId": "f"}
        event = SQSConsumer._normalize_event(body)
        indexer = Indexer(MagicMock())
        assert indexer.process_event(event) is None

    def _consumer(self, indexer: MagicMock) -> SQSConsumer:
        return SQSConsumer(indexer=indexer, queue_url="q", region="us-east-1", endpoint_url="")

    def test_sns_envelope_unwrapped_and_acked(self):
        indexer = MagicMock()
        sqs = MagicMock()
        inner = {"event_type": "document_created", "payload": {"id": "d", "title": "T"}}
        message = {
            "ReceiptHandle": "r",
            "Body": json.dumps({"TopicArn": "arn", "Message": json.dumps(inner)}),
        }
        self._consumer(indexer)._process_message(sqs, message)
        indexer.process_event.assert_called_once_with({"action": "index_document", "data": inner["payload"]})
        sqs.delete_message.assert_called_once_with(QueueUrl="q", ReceiptHandle="r")

    def test_invalid_json_is_dropped(self):
        sqs = MagicMock()
        self._consumer(MagicMock())._process_message(sqs, {"ReceiptHandle": "r", "Body": "{not json"})
        sqs.delete_message.assert_called_once()

    def test_validation_error_is_dropped(self):
        indexer = MagicMock()
        indexer.process_event.side_effect = ValueError("bad")
        sqs = MagicMock()
        self._consumer(indexer)._process_message(sqs, {"ReceiptHandle": "r", "Body": "{}"})
        sqs.delete_message.assert_called_once()

    def test_transient_error_is_left_for_redelivery(self):
        indexer = MagicMock()
        indexer.process_event.side_effect = RuntimeError("meili down")
        sqs = MagicMock()
        self._consumer(indexer)._process_message(sqs, {"ReceiptHandle": "r", "Body": "{}"})
        sqs.delete_message.assert_not_called()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_auth_required_by_default(self, monkeypatch):
        monkeypatch.delenv("REQUIRE_AUTH", raising=False)
        assert AuthConfig().require_auth is True

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("REQUIRE_AUTH", "FALSE")
        monkeypatch.setenv("SQS_ENABLED", "True")
        monkeypatch.setenv("MEILISEARCH_DOCUMENTS_INDEX", "docs-x")
        assert AuthConfig().require_auth is False
        assert SQSConfig().enabled is True
        assert MeiliSearchConfig().documents_index == "docs-x"
